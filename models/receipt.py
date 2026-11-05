# -*- coding: utf-8 -*-
import base64
import binascii
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

PAID_BY = [
    ('cashier', 'Cashier'),
    ('payable', 'Payable'),
    ('unspecified', 'Not specified'),
]

# A cash-out proved by a photo is usually done shortly before the photo is sent, but the photo
# may come late (end of the day). Sessions overlapping this window are suggested for matching.
MATCH_WINDOW_BEFORE = timedelta(hours=18)
MATCH_WINDOW_AFTER = timedelta(hours=2)


class SenderIgnored(Exception):
    """The Telegram sender is archived: the bot stays silent."""


class NotTheSender(Exception):
    """Only the sender of the photo may answer about it."""


class Receipt(models.Model):
    """A bill photo sent by client staff through the DoniaLink Telegram bot, waiting for review.

    Paid by the cashier: the photo is the proof of a POS cash-out, never a second expense.
    Payable: it becomes a "To Pay Later" expense (vendor bill)."""
    _name = 'ecc.receipt'
    _description = 'Telegram Receipt'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sent_at desc, id desc'

    name = fields.Char('Reference', required=True, readonly=True, copy=False, default='New', index=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, readonly=True, index=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    state = fields.Selection([
        ('to_review', 'To Review'),
        ('processed', 'Processed'),
        ('rejected', 'Rejected'),
        ('duplicate', 'Duplicate'),
    ], string='Status', default='to_review', required=True, readonly=True, tracking=True, index=True)
    paid_by = fields.Selection(PAID_BY, string='Paid By', default='unspecified', required=True, tracking=True,
                               help='Answer of the sender in Telegram.\n'
                                    'Cashier: paid from the POS cash drawer, match it to the POS cash-out.\n'
                                    'Payable: not paid yet, record it as a bill to pay.')
    note = fields.Text('Note', tracking=True)

    sender_id = fields.Many2one('ecc.telegram.sender', string='Sent By', readonly=True, index=True)
    sent_at = fields.Datetime('Sent On', required=True, readonly=True, default=fields.Datetime.now, index=True)
    chat_id = fields.Char('Telegram Chat', readonly=True, index=True)
    chat_title = fields.Char('Telegram Group', readonly=True)
    message_id = fields.Integer('Telegram Message', readonly=True,
                                help='Message of the first photo: questions are posted as replies to it.')
    media_group_id = fields.Char('Telegram Album', readonly=True, index=True)

    photo_ids = fields.One2many('ecc.receipt.photo', 'receipt_id', string='Photos')
    photo_count = fields.Integer('Photo Count', compute='_compute_photo_count')
    image = fields.Binary('Photo', compute='_compute_image')

    # Filled in by the accountant
    amount = fields.Monetary('Amount', tracking=True,
                             help='Amount on the bill. Compared with the matched POS cash-out.')
    category_id = fields.Many2one('expense.category', string='Category', tracking=True,
                                  domain="[('company_id', 'in', [False, company_id])]")
    partner_id = fields.Many2one('res.partner', string='Vendor', tracking=True)

    # Result
    expense_id = fields.Many2one('expense.express', string='Expense / Bill', readonly=True, copy=False,
                                 index='btree_not_null', ondelete='set null')
    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', readonly=True, copy=False,
                                        index='btree_not_null', ondelete='set null')
    cash_move_id = fields.Many2one('pos.cash.move', string='POS Cash-Out', copy=False,
                                   index='btree_not_null', ondelete='set null',
                                   domain="[('company_id', '=', company_id), ('move_type', '=', 'out')]")
    session_id = fields.Many2one('pos.session', string='POS Session', index='btree_not_null',
                                 domain="[('company_id', '=', company_id)]",
                                 help='Session open when the photo was sent (or of the matched cash-out).')
    suggested_cash_move_ids = fields.Many2many('pos.cash.move', string='Suggested Cash-Outs',
                                               compute='_compute_suggested_cash_move_ids')
    amount_mismatch = fields.Boolean('Amount Mismatch', compute='_compute_amount_mismatch')
    duplicate_of_id = fields.Many2one('ecc.receipt', string='Possible Duplicate Of', readonly=True, copy=False,
                                      index='btree_not_null', ondelete='set null')
    processed_by_id = fields.Many2one('res.users', string='Processed By', readonly=True, copy=False)
    processed_date = fields.Datetime('Processed On', readonly=True, copy=False)

    question_ids = fields.One2many('ecc.receipt.question', 'receipt_id', string='Questions')
    question_state = fields.Selection([
        ('waiting', 'Waiting for Answer'),
        ('answered', 'Answered'),
    ], string='Question', compute='_compute_question_state', store=True)
    age_days = fields.Integer('Age (days)', compute='_compute_age_days')

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends('photo_ids')
    def _compute_photo_count(self):
        for receipt in self:
            receipt.photo_count = len(receipt.photo_ids)

    @api.depends('photo_ids.attachment_id')
    def _compute_image(self):
        for receipt in self:
            receipt.image = receipt.photo_ids[:1].attachment_id.sudo().datas

    @api.depends('question_ids.state')
    def _compute_question_state(self):
        for receipt in self:
            states = receipt.question_ids.mapped('state')
            receipt.question_state = 'waiting' if 'sent' in states else ('answered' if states else False)

    def _compute_age_days(self):
        now = fields.Datetime.now()
        for receipt in self:
            receipt.age_days = (now - receipt.sent_at).days if receipt.sent_at else 0

    @api.depends('amount', 'cash_move_id.amount_abs', 'expense_id.amount', 'purchase_order_id.amount_total',
                 'currency_id')
    def _compute_amount_mismatch(self):
        for receipt in self:
            if receipt.cash_move_id:
                other = receipt.cash_move_id.amount_abs
            elif receipt.purchase_order_id:
                order = receipt.purchase_order_id
                other = order.amount_total if order.order_line else None
            elif receipt.expense_id:
                other = receipt.expense_id.amount
            else:
                other = None
            receipt.amount_mismatch = bool(
                receipt.amount and other is not None
                and float_compare(receipt.amount, other, precision_rounding=receipt.currency_id.rounding or 0.01))

    @api.depends('sent_at', 'company_id', 'session_id', 'amount', 'state')
    def _compute_suggested_cash_move_ids(self):
        for receipt in self:
            if receipt.state == 'to_review' and receipt.id:
                receipt.suggested_cash_move_ids = receipt._candidate_cash_moves()
            else:
                receipt.suggested_cash_move_ids = False

    def _candidate_sessions(self):
        """Sessions of the company running around the time the photo was sent."""
        self.ensure_one()
        if not self.sent_at:
            return self.env['pos.session']
        return self.env['pos.session'].search([
            ('company_id', '=', self.company_id.id),
            ('start_at', '<=', self.sent_at + MATCH_WINDOW_AFTER),
            '|', ('stop_at', '=', False), ('stop_at', '>=', self.sent_at - MATCH_WINDOW_BEFORE),
        ], order='start_at desc')

    def _candidate_cash_moves(self, limit=20):
        """Cash-outs this photo may prove: those of the receipt's session (or of the sessions running when
        it was sent), the ones without a receipt first, then the closest amount, then the closest time."""
        self.ensure_one()
        sessions = self.session_id or self._candidate_sessions()
        if not sessions:
            return self.env['pos.cash.move']
        moves = self.env['pos.cash.move'].search([
            ('session_id', 'in', sessions.ids), ('move_type', '=', 'out'),
        ])
        amount = self.amount
        sent_at = self.sent_at

        def key(move):
            when = move.statement_line_id.create_date or sent_at
            return (bool(move.receipt_ids), abs(move.amount_abs - amount) if amount else 0,
                    abs((when - sent_at).total_seconds()))
        return moves.sorted(key)[:limit]

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('ecc.receipt') or 'New'
        return super().create(vals_list)

    def _guess_session(self):
        """Set the session when exactly one session was open when the photo was sent."""
        for receipt in self.filtered(lambda r: not r.session_id and r.sent_at):
            running = receipt._candidate_sessions().filtered(
                lambda s: s.start_at and s.start_at <= receipt.sent_at
                and (not s.stop_at or s.stop_at >= receipt.sent_at))
            if len(running) == 1:
                receipt.session_id = running

    # ------------------------------------------------------------------
    # Photos
    # ------------------------------------------------------------------

    def _add_photo(self, content, filename=None, mimetype=None, message_id=None, file_unique_id=None):
        """Store one photo on the receipt and flag a possible duplicate."""
        self.ensure_one()
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename or '%s-%s.jpg' % (self.name, len(self.photo_ids) + 1),
            'raw': content,
            'mimetype': mimetype or 'image/jpeg',
            'res_model': self._name,
            'res_id': self.id,
        })
        photo = self.env['ecc.receipt.photo'].sudo().create({
            'receipt_id': self.id,
            'attachment_id': attachment.id,
            'chat_id': self.chat_id,
            'message_id': message_id,
            'file_unique_id': file_unique_id or False,
            'checksum': attachment.checksum,
        })
        if not self.duplicate_of_id:
            original = photo._find_original()
            if original:
                self.sudo().duplicate_of_id = original
        return photo

    # ------------------------------------------------------------------
    # Telegram (called by the agent tools)
    # ------------------------------------------------------------------

    @api.model
    def _telegram_create(self, company, chat_id, message_id, sender, photo, chat_title=None,
                         media_group_id=None, sent_at=None, caption=None):
        """One photo message from a client group. Idempotent on (chat, message): the platform may
        send a message again. Returns (receipt, is_new_receipt); raises SenderIgnored for an
        archived sender."""
        chat_id = str(chat_id)
        Photo = self.env['ecc.receipt.photo'].sudo()
        existing = Photo.search([('chat_id', '=', chat_id), ('message_id', '=', message_id)], limit=1)
        if existing:
            return existing.receipt_id, False

        person = self.env['ecc.telegram.sender'].sudo()._find_or_create(
            company, sender['telegram_user_id'], sender.get('name'), sender.get('username'))
        if not person.active:
            raise SenderIgnored()

        try:
            content = base64.b64decode(photo['content_b64'], validate=True)
        except (binascii.Error, ValueError) as e:
            raise UserError(_('The photo is not valid base64.')) from e
        if not content:
            raise UserError(_('The photo is empty.'))

        receipt = self.browse()
        if media_group_id:
            receipt = self.sudo().search([
                ('company_id', '=', company.id), ('chat_id', '=', chat_id),
                ('media_group_id', '=', str(media_group_id)),
            ], limit=1)
        is_new = not receipt
        if is_new:
            receipt = self.sudo().with_company(company).create({
                'company_id': company.id,
                'chat_id': chat_id,
                'chat_title': chat_title or False,
                'message_id': message_id,
                'media_group_id': str(media_group_id) if media_group_id else False,
                'sender_id': person.id,
                'sent_at': sent_at or fields.Datetime.now(),
                'note': (caption or '').strip() or False,
            })
            receipt._guess_session()
        elif caption and caption.strip() and not receipt.note:
            receipt.note = caption.strip()
        receipt._add_photo(content, photo.get('filename'), photo.get('mimetype'), message_id,
                           photo.get('file_unique_id'))
        return receipt, is_new

    def _telegram_update(self, telegram_user_id, paid_by=None, note=None):
        """Answers of the sender to the bot's questions. Ignored once the receipt is reviewed."""
        self.ensure_one()
        if str(telegram_user_id) != self.sender_id.telegram_user_id:
            raise NotTheSender()
        if self.state == 'to_review':
            vals = {}
            if paid_by:
                vals['paid_by'] = paid_by
            if note and note.strip():
                vals['note'] = note.strip()
            if vals:
                self.sudo().write(vals)
        return self

    def _paid_by_label(self):
        self.ensure_one()
        return dict(self._fields['paid_by']._description_selection(self.env))[self.paid_by]

    def _telegram_summary(self):
        """The bot's confirmation: "✅ Received R-0153 — Cashier · gas cylinder"."""
        self.ensure_one()
        text = _('✅ Received %(ref)s — %(paid_by)s', ref=self.name, paid_by=self._paid_by_label())
        if self.note:
            text += ' · %s' % self.note.splitlines()[0][:100]
        return text

    def _telegram_post_reply(self, sender, text):
        """A message from the Telegram group about this receipt: kept in the chatter."""
        self.ensure_one()
        name = sender.name if sender else _('Telegram')
        self.sudo().message_post(
            body=_('💬 %(name)s (Telegram): %(text)s', name=name, text=text),
            message_type='comment', subtype_xmlid='mail.mt_comment')

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _check_to_review(self):
        for receipt in self:
            if receipt.state != 'to_review':
                raise UserError(_('Receipt %s is already closed. Reset it to "To Review" first.', receipt.name))

    def _close(self, state):
        self.write({'state': state, 'processed_by_id': self.env.user.id, 'processed_date': fields.Datetime.now()})

    def action_create_purchase_order(self):
        """Open a new RFQ prefilled from the receipt (vendor, date, note, photo); the accountant adds the
        product lines and confirms it. Saving it links it here and copies the photos on it."""
        self.ensure_one()
        self._check_to_review()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Order from %s', self.name),
            'res_model': 'purchase.order',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {'ecc_receipt_id': self.id},
        }

    def _purchase_defaults(self):
        self.ensure_one()
        values = {'origin': self.name}
        if self.partner_id:
            values['partner_id'] = self.partner_id.id
        if self.sent_at:
            values['date_order'] = self.sent_at
        return values

    def _link_purchase_order(self, order):
        """Called when the purchase order opened from the receipt is saved."""
        self.ensure_one()
        copies = self._copy_photos(order)
        body = _('Telegram receipt %s.', self._get_html_link())
        if self.note:
            body = _('Telegram receipt %(ref)s: %(note)s', ref=self._get_html_link(), note=self.note)
        order.message_post(body=body, attachment_ids=copies.ids)
        vals = {'purchase_order_id': order.id}
        if not self.partner_id:
            vals['partner_id'] = order.partner_id.id
        self.write(vals)
        self._close('processed')
        self.message_post(body=_('Recorded as purchase order %s.', order._get_html_link()))

    def _copy_photos(self, record):
        copies = self.env['ir.attachment']
        for photo in self.photo_ids:
            copies |= photo.attachment_id.sudo().copy({'res_model': record._name, 'res_id': record.id})
        return copies

    def action_open_purchase_order(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'purchase.order', 'res_id': self.purchase_order_id.id,
                'views': [(False, 'form')], 'target': 'current'}

    def action_create_bill(self):
        """Open a new expense prefilled from the receipt ("To Pay Later" unless the cashier paid it), for
        costs that are not stock purchases; saving it links it here and copies the photos on it."""
        self.ensure_one()
        self._check_to_review()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bill from %s', self.name),
            'res_model': 'expense.express',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {'ecc_receipt_id': self.id},
        }

    def _expense_defaults(self):
        self.ensure_one()
        values = {
            'payment_mode': 'to_pay',
            'name': self.note.splitlines()[0][:120] if self.note else self.name,
            'notes': _('Telegram receipt %(ref)s sent by %(sender)s.', ref=self.name,
                       sender=self.sender_id.name or '-'),
        }
        if self.sent_at:
            values['date'] = fields.Datetime.context_timestamp(self, self.sent_at).date()
        if self.amount:
            values['amount'] = self.amount
        if self.category_id:
            values['category_id'] = self.category_id.id
        if self.partner_id:
            values['partner_id'] = self.partner_id.id
        return values

    def _link_expense(self, expense):
        """Called when the expense opened from the receipt is saved."""
        self.ensure_one()
        copies = self._copy_photos(expense)
        if copies:
            expense.write({'attachment_ids': [(4, a.id) for a in copies]})
        vals = {'expense_id': expense.id}
        if not self.amount:
            vals['amount'] = expense.amount
        if not self.category_id and expense.category_id:
            vals['category_id'] = expense.category_id.id
        if not self.partner_id and expense.partner_id:
            vals['partner_id'] = expense.partner_id.id
        self.write(vals)
        self._close('processed')
        self.message_post(body=_('Recorded as expense %s.', expense._get_html_link()))

    def action_match_cash_move(self):
        """Match with the cash-out of the clicked row (context) or of the POS Cash-Out field."""
        self.ensure_one()
        move_id = self.env.context.get('ecc_cash_move_id')
        move = self.env['pos.cash.move'].browse(move_id) if move_id else self.cash_move_id
        if not move:
            raise UserError(_('Choose the POS cash-out this receipt proves.'))
        return self._match_cash_move(move)

    def _match_cash_move(self, move):
        """The photo proves this cash-out: link it, attach the photos on the cash-out and classify the
        cash-out with the receipt's category when it is not classified yet. No new expense is recorded."""
        self.ensure_one()
        self._check_to_review()
        move.ensure_one()
        if move.move_type != 'out':
            raise UserError(_('Only a Cash Out can be proved by a receipt.'))
        if move.company_id != self.company_id:
            raise UserError(_('The cash-out belongs to another company.'))
        if move.state == 'to_classify':
            if move.classification_type == 'category':
                category = self.category_id or move.category_id
                if not category:
                    raise UserError(_('Choose the category of the receipt first: the cash-out "%s" is not '
                                      'classified yet and is classified with it.', move.name))
                move.category_id = category
            move.action_classify()
        copies = self._copy_photos(move)
        move.message_post(body=_('Receipt %s attached as proof.', self._get_html_link()),
                          attachment_ids=copies.ids)
        vals = {'cash_move_id': move.id, 'session_id': move.session_id.id}
        if not self.category_id and move.category_id:
            vals['category_id'] = move.category_id.id
        self.write(vals)
        self._close('processed')
        self.message_post(body=_('Matched to POS cash-out %(move)s (%(session)s).',
                                 move=move._get_html_link(), session=move.session_id.name or '-'))
        if self.amount_mismatch:
            self.message_post(body=_('⚠️ Amount on the receipt %(receipt)s, on the cash-out %(move)s.',
                                     receipt=self.currency_id.format(self.amount),
                                     move=self.currency_id.format(move.amount_abs)))
        return True

    def action_reject(self):
        self._check_to_review()
        self._close('rejected')
        return True

    def action_mark_duplicate(self):
        self._check_to_review()
        self._close('duplicate')
        return True

    def action_reset_to_review(self):
        """Reopen the receipt. A recorded expense and the cash-out classification stay as they are;
        only the link to the cash-out is removed."""
        self.write({'state': 'to_review', 'cash_move_id': False, 'processed_by_id': False, 'processed_date': False})
        return True

    def action_ask_question(self):
        self.ensure_one()
        if not self.chat_id or not self.message_id:
            raise UserError(_('This receipt did not come from Telegram.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ask a Question'),
            'res_model': 'ecc.receipt.question.wizard',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_receipt_id': self.id},
        }

    def action_open_expense(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'expense.express', 'res_id': self.expense_id.id,
                'views': [(False, 'form')], 'target': 'current'}

    def action_open_duplicate(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.duplicate_of_id.id,
                'views': [(False, 'form')], 'target': 'current'}


class ReceiptPhoto(models.Model):
    _name = 'ecc.receipt.photo'
    _description = 'Telegram Receipt Photo'
    _order = 'id'

    receipt_id = fields.Many2one('ecc.receipt', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='receipt_id.company_id', store=True, index=True)
    attachment_id = fields.Many2one('ir.attachment', required=True, ondelete='cascade')
    image = fields.Binary(related='attachment_id.datas', string='Photo')
    chat_id = fields.Char(index=True)
    message_id = fields.Integer(index=True)
    file_unique_id = fields.Char('Telegram File ID', index=True,
                                 help='Telegram keeps the same value when the photo is forwarded.')
    checksum = fields.Char(index=True)

    _sql_constraints = [
        ('chat_message_unique', 'UNIQUE(chat_id, message_id)', 'This Telegram message is already a receipt.'),
    ]

    def _find_original(self):
        """An earlier receipt of the same company with the same picture (same Telegram file or same bytes)."""
        self.ensure_one()
        keys = []
        if self.file_unique_id:
            keys.append(('file_unique_id', '=', self.file_unique_id))
        if self.checksum:
            keys.append(('checksum', '=', self.checksum))
        if not keys:
            return self.env['ecc.receipt']
        domain = [('company_id', '=', self.company_id.id), ('receipt_id', '!=', self.receipt_id.id)]
        domain += (['|'] + keys) if len(keys) == 2 else keys
        return self.search(domain, order='id', limit=1).receipt_id


class ReceiptQuestion(models.Model):
    """A question of the accountant, posted by the bot as a reply under the photo."""
    _name = 'ecc.receipt.question'
    _description = 'Telegram Receipt Question'
    _order = 'id desc'

    receipt_id = fields.Many2one('ecc.receipt', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='receipt_id.company_id', store=True)
    text = fields.Text('Question', required=True)
    user_id = fields.Many2one('res.users', string='Asked By', default=lambda self: self.env.user)
    chat_id = fields.Char(index=True)
    telegram_message_id = fields.Integer('Telegram Message', index=True)
    state = fields.Selection([('sent', 'Waiting'), ('answered', 'Answered')], default='sent', required=True)
    answer = fields.Text('Answer')
    answered_by_id = fields.Many2one('ecc.telegram.sender', string='Answered By')
    answer_date = fields.Datetime('Answered On')
