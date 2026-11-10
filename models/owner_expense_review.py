# -*- coding: utf-8 -*-
"""An owner expense is cash out of the owner's box (or paid with a card), like a POS cash-out: it is booked at
once on the category the owner chose, and the accountant reviews it on the movement itself: it stays an expense
(the category can be changed), becomes a payment to a vendor (on the vendor account: it shows on the vendor's
bills as an outstanding payment to apply), or is rejected (the amount goes back).
No receipt is created in the Receipts inbox; the photos are on the expense / the payment."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class OwnerExpenseReview(models.AbstractModel):
    _name = 'ecc.owner.expense.mixin'
    _description = 'Owner expense to review'

    review_state = fields.Selection([
        ('to_review', 'To Review'), ('reviewed', 'Reviewed'), ('rejected', 'Rejected'),
    ], string='Review', copy=False, index='btree_not_null', readonly=True)
    vendor_id = fields.Many2one('res.partner', string='Vendor', copy=False,
                                help='Who was paid: choose it, then "Vendor Payment" when it was not an expense.')
    vendor_entry_id = fields.Many2one('account.move', string='Payment to Vendor', readonly=True, copy=False,
                                      ondelete='set null')
    review_as = fields.Selection([('expense', 'Expense'), ('vendor', 'Payment to a vendor')],
                                 string='It was', default='expense', copy=False,
                                 help='Expense: a cost of the business, on the category.\n'
                                      'Payment to a vendor: the owner paid a supplier (goods, a bill); it goes on the '
                                      "vendor's account and is applied to his bills.")
    photo = fields.Binary('Photo', compute='_compute_review_attachments')
    photo_count = fields.Integer('Photos', compute='_compute_review_attachments')
    attachment_ids = fields.Many2many('ir.attachment', compute='_compute_review_attachments', string='Photos')
    # category_id: related to the expense, declared on each movement model (the mixin has no expense_id)

    def _review_card(self):
        return self.env['ecc.owner.card']

    def _review_box(self):
        return self.box_id

    @api.depends('amount')
    def _compute_review_amount(self):
        for move in self:
            move.review_amount = abs(move.amount)

    @api.depends('vendor_entry_id')
    def _compute_review_attachments(self):
        Attachment = self.env['ir.attachment'].sudo()
        for move in self:
            if move.expense_id:
                attachments = move.expense_id.sudo().attachment_ids
            elif move.vendor_entry_id:
                attachments = Attachment.search([('res_model', '=', 'account.move'),
                                                 ('res_id', '=', move.vendor_entry_id.id)])
            else:
                attachments = Attachment
            move.attachment_ids = attachments
            move.photo_count = len(attachments)
            image = attachments.filtered(lambda a: (a.mimetype or '').startswith('image/'))[:1]
            move.photo = image.datas if image else False

    def _check_to_review(self):
        for move in self:
            if move.review_state != 'to_review':
                raise UserError(_('"%s" is not waiting for review.', move.name))

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------

    _review_form = None   # xml id of the review form of the model

    def action_open_review(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'views': [(self.env.ref(self._review_form).id, 'form')], 'target': 'current',
                'name': self.name}

    def action_review_confirm(self):
        """The one button of the review: as an expense or as a payment to the vendor, as chosen."""
        for move in self:
            if move.review_as == 'vendor':
                move.action_review_vendor()
            else:
                move.action_review_done()
        return True

    def action_review_done(self):
        """It is an expense of the business (category checked): final."""
        self._check_to_review()
        self.write({'review_state': 'reviewed'})
        self._push_review('reviewed')
        return True

    def action_review_reject(self):
        """Not a business expense: removed, the amount goes back to the owner's box / the card."""
        self._check_to_review()
        for move in self:
            expense = move.expense_id
            move.write({'review_state': 'rejected', 'state': 'cancelled', 'expense_id': False})
            if expense:
                expense.sudo().unlink()
        self._push_review('rejected')
        return True

    def action_review_vendor(self):
        """The owner paid a vendor (goods, a bill), not an expense: the expense is replaced by a payment on the
        vendor account from the same box / card (the owner's balance does not change). No purchase order: the
        payment shows on the vendor's bills as an outstanding payment, applied with "Add"."""
        self.ensure_one()
        self._check_to_review()
        vendor = self.vendor_id.commercial_partner_id
        if not vendor:
            raise UserError(_('Choose the vendor first.'))
        expense = self.expense_id
        if not expense:
            raise UserError(_('This movement has no expense to turn into a payment.'))
        company = expense.company_id
        payable = vendor.with_company(company).property_account_payable_id
        if not payable:
            raise UserError(_('The vendor "%s" has no payable account.', vendor.display_name))
        journal = expense.journal_id
        amount = expense.amount
        label = _('Payment to %(vendor)s – %(owner)s', vendor=vendor.display_name, owner=self._review_box().name)
        entry = self.env['account.move'].sudo().create({
            'move_type': 'entry', 'journal_id': journal.id, 'date': expense.date, 'ref': label,
            'company_id': company.id,
            'line_ids': [
                (0, 0, {'name': label, 'account_id': payable.id, 'partner_id': vendor.id, 'debit': amount}),
                (0, 0, {'name': label, 'account_id': journal.default_account_id.id, 'partner_id': vendor.id,
                        'credit': amount}),
            ],
        })
        entry.action_post()
        for attachment in expense.sudo().attachment_ids:
            attachment.copy({'res_model': 'account.move', 'res_id': entry.id})
        self.write({'expense_id': False, 'vendor_entry_id': entry.id, 'account_move_id': entry.id, 'name': label,
                    'vendor_id': vendor.id, 'review_state': 'reviewed', 'review_as': 'vendor'})
        expense.sudo().unlink()
        self._push_review('reviewed')
        return True

    # ------------------------------------------------------------------
    # Owner notification
    # ------------------------------------------------------------------

    def _push_review(self, state):
        """Tell the owner his expense (cash box or card) was reviewed or rejected."""
        for move in self:
            box = move._review_box()
            if not box:
                continue
            card = move._review_card()
            rec = move.with_context(lang=box._app_lang()).sudo()
            env = rec.env
            amount = abs(rec.amount)
            what = '%s · %s' % (rec.currency_id.format(amount), rec.name)
            if state == 'reviewed':
                title, body = env._('Expense reviewed ✓'), what
            else:
                back = (env._('The amount is back on the card %s.', card.name) if card
                        else env._('The amount is back in your cash box.'))
                title, body = env._('Expense rejected'), '%s · %s' % (what, back)
            kind = 'expense_reviewed' if state == 'reviewed' else 'expense_rejected'
            box._owner_notify(kind, '%s\n%s' % (title, body), title, body=body,
                              route='bankcard' if card else 'moves', card=card or None,
                              tag='owner-expense-%s-%s' % (move._name, move.id),
                              data={'move_id': move.id, 'card_move': bool(card), 'amount': amount,
                                    'reference': move.name, 'receipt_id': None})


class OwnerMove(models.Model):
    _name = 'ecc.owner.move'
    _inherit = ['ecc.owner.move', 'ecc.owner.expense.mixin']
    _review_form = 'expense_cash_control_telegram.view_ecc_owner_move_review_form'

    category_id = fields.Many2one(related='expense_id.category_id', readonly=False, string='Category')
    review_amount = fields.Monetary('Paid', compute='_compute_review_amount', currency_field='currency_id')


class OwnerCardMove(models.Model):
    _name = 'ecc.owner.card.move'
    _inherit = ['ecc.owner.card.move', 'ecc.owner.expense.mixin']
    _review_form = 'expense_cash_control_telegram.view_ecc_owner_card_move_review_form'

    category_id = fields.Many2one(related='expense_id.category_id', readonly=False, string='Category')
    review_amount = fields.Monetary('Paid', compute='_compute_review_amount', currency_field='currency_id')

    def _review_card(self):
        return self.card_id
