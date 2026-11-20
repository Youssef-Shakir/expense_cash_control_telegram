# -*- coding: utf-8 -*-
"""Receipts sent from the DoniaLink App (/dl/app#receipt). (Was the module donialink_app_receipts.)"""
import logging

from odoo import _, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


class DoniaLinkAppReceipts(http.Controller):

    def _receipts(self):
        return request.env['ecc.receipt'].sudo()

    def _own(self, receipt_id):
        receipt = self._receipts().browse(int(receipt_id or 0)).exists()
        if not receipt or receipt.app_user_id != request.env.user:
            raise UserError(_('This receipt is no longer here.'))
        return receipt

    @http.route('/dl/app/receipts/api/<string:action>', type='json', auth='user', methods=['POST'])
    def api(self, action, **kw):
        user = request.env.user
        try:
            if action == 'send':
                if not user.has_group('expense_cash_control_telegram.group_receipt_sender'):
                    raise AccessError(_('You may not send receipts.'))
                receipt = self._receipts()._app_create(
                    user, kw.get('photos') or [], paid_by=kw.get('paid_by'), note=kw.get('note'),
                    amount=kw.get('amount'))
                return receipt._app_to_app()[0]
            if action == 'mine':
                domain = [('app_user_id', '=', user.id)]
                if kw.get('before'):
                    domain.append(('id', '<', int(kw['before'])))
                receipts = self._receipts().search(domain, limit=min(int(kw.get('limit') or 20), 50),
                                                   order='id desc')
                return {'receipts': receipts._app_to_app()}
            if action == 'receipt':
                return self._own(kw.get('receipt_id'))._app_to_app(full=True)[0]
            if action == 'answer':
                receipt = self._own(kw.get('receipt_id'))
                receipt._app_answer(user, kw.get('question_id') or 0, kw.get('text'))
                return receipt._app_to_app(full=True)[0]
            return {'error': 'unknown', 'message': _('Unknown action.')}
        except (UserError, AccessError) as e:
            return {'error': 'user', 'message': str(e.args[0] if e.args else e)}

    @http.route('/dl/app/receipts/photo/<int:photo_id>', type='http', auth='user')
    def photo(self, photo_id, **kw):
        photo = request.env['ecc.receipt.photo'].sudo().browse(photo_id).exists()
        if not photo or photo.receipt_id.app_user_id != request.env.user:
            raise request.not_found()
        return request.env['ir.binary']._get_stream_from(photo.attachment_id).get_response(
            max_age=86400, immutable=True)
