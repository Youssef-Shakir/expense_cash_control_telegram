# -*- coding: utf-8 -*-
import base64
import binascii

from odoo import _, api, fields, models
from odoo.exceptions import UserError

MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 8 * 1024 * 1024
APP_PAID_BY = ('cashier', 'payable', 'unspecified')


class Receipt(models.Model):
    _inherit = 'ecc.receipt'

    app_user_id = fields.Many2one('res.users', string='Sent from the App by', readonly=True, index='btree_not_null',
                                  ondelete='set null')

    # ------------------------------------------------------------------
    # From the app
    # ------------------------------------------------------------------

    @api.model
    def _app_create(self, user, photos, paid_by='unspecified', note=None, amount=None):
        """A receipt sent from the DoniaLink App by ``user``: photos [{content_b64, filename, mimetype}]."""
        if not photos:
            raise UserError(_('Add a photo of the bill.'))
        if len(photos) > MAX_PHOTOS:
            raise UserError(_('At most %s photos per receipt.', MAX_PHOTOS))
        contents = []
        for photo in photos:
            try:
                content = base64.b64decode((photo or {}).get('content_b64') or '', validate=True)
            except (binascii.Error, ValueError) as e:
                raise UserError(_('A photo could not be read. Take it again.')) from e
            if not content:
                raise UserError(_('A photo is empty. Take it again.'))
            if len(content) > MAX_PHOTO_BYTES:
                raise UserError(_('A photo is too large.'))
            mimetype = str(photo.get('mimetype') or 'image/jpeg')
            if not mimetype.startswith('image/'):
                raise UserError(_('Only photos can be sent.'))
            contents.append((content, str(photo.get('filename') or '')[:120] or None, mimetype))
        company = user.company_id
        vals = {
            'company_id': company.id,
            'app_user_id': user.id,
            'paid_by': paid_by if paid_by in APP_PAID_BY else 'unspecified',
            'note': (note or '').strip()[:1000] or False,
        }
        if amount:
            try:
                vals['amount'] = max(float(amount), 0.0)
            except (TypeError, ValueError):
                pass
        receipt = self.sudo().with_company(company).create(vals)
        receipt._guess_session()
        for content, filename, mimetype in contents:
            receipt._add_photo(content, filename, mimetype)
        receipt.message_post(body=_('📱 Sent from the DoniaLink App by %s.', user.name),
                             message_type='comment', subtype_xmlid='mail.mt_note')
        receipt._app_notify_accountants()
        return receipt

    def _app_notify_accountants(self):
        self.ensure_one()
        body = '%s · %s' % (self._paid_by_label(), self.note.splitlines()[0][:120]) if self.note \
            else self._paid_by_label()
        self.env['donialink.app.message'].sudo().send(
            'receipt_new', _('New receipt %(ref)s from %(name)s', ref=self.name, name=self.app_user_id.name),
            body, company=self.company_id, url='/odoo/ecc.receipt/%s' % self.id,
            sender=self.app_user_id.name, origin='ecc_receipts_app')

    def _app_tell_sender(self, title, body, url=None):
        for receipt in self.filtered('app_user_id'):
            self.env['donialink.app.message'].sudo().send(
                'receipt_staff', title, body, users=receipt.app_user_id, company=receipt.company_id,
                url=url or '#receipt/%s' % receipt.id, origin='ecc_receipts_app')

    def _app_to_app(self, full=False):
        state_labels = dict(self._fields['state']._description_selection(self.env))
        out = []
        for r in self:
            value = {
                'id': r.id, 'reference': r.name, 'state': r.state, 'state_label': state_labels.get(r.state, ''),
                'paid_by': r.paid_by, 'paid_by_label': r._paid_by_label(), 'note': r.note or '',
                'amount': r.amount or 0.0, 'amount_text': r.currency_id.format(r.amount) if r.amount else '',
                'date': fields.Datetime.to_string(r.sent_at), 'photo_count': len(r.photo_ids),
                'waiting_question': any(q.state == 'sent' for q in r.question_ids),
            }
            if full:
                value['questions'] = [{
                    'id': q.id, 'text': q.text, 'answer': q.answer or '', 'state': q.state,
                    'by': q.user_id.name or '', 'date': fields.Datetime.to_string(q.create_date),
                } for q in r.question_ids.sorted('id')]
                value['photos'] = ['/dl/app/receipts/photo/%s' % p.id for p in r.photo_ids]
            out.append(value)
        return out

    def _app_answer(self, user, question_id, text):
        """The sender answers the accountant's question in the app: kept in the chatter."""
        self.ensure_one()
        text = (text or '').strip()
        if not text:
            raise UserError(_('Write the answer first.'))
        question = self.question_ids.filtered(lambda q: q.id == int(question_id))
        if not question:
            raise UserError(_('This question is no longer here.'))
        question.sudo().write({'state': 'answered', 'answer': text[:2000], 'answer_date': fields.Datetime.now()})
        self.sudo().message_post(body=_('💬 %(name)s (DoniaLink App): %(text)s', name=user.name, text=text),
                                 message_type='comment', subtype_xmlid='mail.mt_comment')
        asker = question.user_id
        if asker and asker.active:
            self.env['donialink.app.message'].sudo().send(
                'general', _('Answer on %s', self.name), text, users=asker, company=self.company_id,
                url='/odoo/ecc.receipt/%s' % self.id, sender=user.name, origin='ecc_receipts_app')
        return question

    @api.model
    def dl_app_open_questions(self):
        """The badge on the "Send receipt" tile: questions waiting for this person's answer."""
        return self.env['ecc.receipt.question'].sudo().search_count([
            ('receipt_id.app_user_id', '=', self.env.uid), ('state', '=', 'sent')])

    # ------------------------------------------------------------------
    # The accountant's actions, for receipts sent from the app
    # ------------------------------------------------------------------

    def action_ask_question(self):
        self.ensure_one()
        if self.app_user_id and not self.chat_id:
            return {
                'type': 'ir.actions.act_window', 'name': _('Ask a Question'),
                'res_model': 'ecc.receipt.question.wizard', 'views': [(False, 'form')], 'target': 'new',
                'context': {'default_receipt_id': self.id},
            }
        return super().action_ask_question()

    def _close(self, state):
        result = super()._close(state)
        labels = {'processed': _('Receipt %s reviewed ✓'), 'rejected': _('Receipt %s rejected'),
                  'duplicate': _('Receipt %s is a duplicate')}
        for receipt in self.filtered('app_user_id'):
            receipt._app_tell_sender(labels.get(state, '%s') % receipt.name,
                                     receipt.note or receipt._paid_by_label())
        return result
