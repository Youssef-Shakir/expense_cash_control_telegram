# -*- coding: utf-8 -*-
"""Agent tools called by the DoniaLink Platform's Telegram bot (receipt capture).

The platform runs the conversation in the client's group (buttons, 15-minute timeout) and calls:

    receipt_create  once per photo message (an album = several calls, grouped by media_group_id)
    receipt_update  with the sender's answers (who paid, note)
    receipt_reply   when someone replies under a question of the accountant (or under the photo)

They are write tools of category "receipts": the platform allows exactly these for the bot flow.
Error codes the bot relies on: sender_ignored (stay silent), not_found (ignore), not_the_sender.
"""
import pytz
from dateutil import parser as date_parser

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.donialink_agent.models.agent_registry import ACCESS_WRITE, ToolError, agent_tool

from .receipt import NotTheSender, SenderIgnored

COMPANY = {'type': 'integer', 'description': 'Company of the Telegram group (see instance_info).'}
CHAT_ID = {'type': 'string', 'maxLength': 64, 'description': 'Telegram chat id of the group.'}
SENDER = {
    'type': 'object',
    'description': 'Telegram user who sent the message.',
    'properties': {
        'telegram_user_id': {'type': 'string', 'maxLength': 64},
        'name': {'type': 'string', 'maxLength': 200, 'nullable': True},
        'username': {'type': 'string', 'maxLength': 100, 'nullable': True},
    },
    'required': ['telegram_user_id'],
}
REQUIRES = ('ecc.receipt',)


class AgentTools(models.AbstractModel):
    _inherit = 'donialink.agent.tools'

    @api.model
    def _receipt_company(self, company_id):
        company = self.env['res.company'].sudo().browse(company_id).exists()
        if not company:
            raise ToolError('invalid_params', f'No company with id {company_id}')
        return company

    @api.model
    def _receipt_datetime(self, value):
        if not value:
            return fields.Datetime.now()
        try:
            moment = date_parser.isoparse(value)
        except (ValueError, OverflowError) as e:
            raise ToolError('invalid_params', "'sent_at' must be an ISO date-time") from e
        if moment.tzinfo:
            moment = moment.astimezone(pytz.utc).replace(tzinfo=None)
        return moment

    @api.model
    def _receipt_payload(self, receipt, **extra):
        payload = {
            'receipt_id': receipt.id,
            'reference': receipt.name,
            'state': receipt.state,
            'paid_by': receipt.paid_by,
            'note': receipt.note or None,
            'photo_count': receipt.photo_count,
            'duplicate_of': {'id': receipt.duplicate_of_id.id, 'reference': receipt.duplicate_of_id.name}
            if receipt.duplicate_of_id else None,
            'summary_text': receipt._telegram_summary(),
        }
        payload.update(extra)
        return payload

    @agent_tool(
        name='receipt_create',
        title='Receive a receipt photo', title_ar='استلام صورة فاتورة',
        category='receipts', access=ACCESS_WRITE, requires=REQUIRES,
        description="""Store one bill photo posted in a client's Telegram group as a receipt to review
        (Expenses & Cash > POS Cash > Receipts). Call once per photo message. Photos of the same album
        (same media_group_id) join one receipt. Calling again with the same chat_id and message_id returns
        the existing receipt (is_new_receipt false). Returns the reference (R-0153) to show to the sender and
        duplicate_of when the same picture was already received. Error sender_ignored: the sender is archived
        in Odoo, do not answer.""",
        params={
            'type': 'object',
            'properties': {
                'company_id': COMPANY,
                'chat_id': CHAT_ID,
                'chat_title': {'type': 'string', 'maxLength': 200, 'nullable': True},
                'message_id': {'type': 'integer', 'description': 'Telegram message id of the photo.'},
                'media_group_id': {'type': 'string', 'maxLength': 64, 'nullable': True,
                                   'description': 'Telegram album id, when the photo is part of an album.'},
                'sender': SENDER,
                'sent_at': {'type': 'string', 'nullable': True,
                            'description': 'When the photo was sent, ISO 8601 (UTC). Default: now.'},
                'caption': {'type': 'string', 'maxLength': 1024, 'nullable': True},
                'photo': {
                    'type': 'object',
                    'properties': {
                        'filename': {'type': 'string', 'maxLength': 200, 'nullable': True},
                        'mimetype': {'type': 'string', 'maxLength': 100, 'nullable': True},
                        'content_b64': {'type': 'string', 'description': 'The image, base64.'},
                        'file_unique_id': {'type': 'string', 'maxLength': 100, 'nullable': True,
                                           'description': 'Telegram file_unique_id (duplicate detection).'},
                    },
                    'required': ['content_b64'],
                },
            },
            'required': ['company_id', 'chat_id', 'message_id', 'sender', 'photo'],
        },
    )
    def _tool_receipt_create(self, company_id, chat_id, message_id, sender, photo, chat_title=None,
                             media_group_id=None, sent_at=None, caption=None):
        company = self._receipt_company(company_id)
        try:
            receipt, is_new = self.env['ecc.receipt'].sudo().with_company(company)._telegram_create(
                company, chat_id, message_id, sender, photo, chat_title=chat_title,
                media_group_id=media_group_id, sent_at=self._receipt_datetime(sent_at), caption=caption)
        except SenderIgnored as e:
            raise ToolError('sender_ignored', 'This Telegram user is archived in Odoo: ignore the message.') from e
        except UserError as e:
            raise ToolError('invalid_photo', str(e)) from e
        return self._receipt_payload(receipt, is_new_receipt=is_new)

    @agent_tool(
        name='receipt_update',
        title='Answer about a receipt', title_ar='إجابة عن فاتورة',
        category='receipts', access=ACCESS_WRITE, requires=REQUIRES,
        description="""Save the sender's answers to the bot about a receipt created by receipt_create: who paid
        the bill (cashier = from the POS cash drawer, payable = to pay later) and an optional note. Only the
        original sender may answer (error not_the_sender). Answers are ignored once the accountant reviewed the
        receipt. Returns summary_text, the confirmation to post (e.g. "✅ Received R-0153 — Cashier · gas").""",
        params={
            'type': 'object',
            'properties': {
                'receipt_id': {'type': 'integer'},
                'telegram_user_id': {'type': 'string', 'maxLength': 64,
                                     'description': 'Telegram user who answered.'},
                'paid_by': {'type': 'string', 'enum': ['cashier', 'payable'], 'nullable': True},
                'note': {'type': 'string', 'maxLength': 1000, 'nullable': True},
            },
            'required': ['receipt_id', 'telegram_user_id'],
        },
    )
    def _tool_receipt_update(self, receipt_id, telegram_user_id, paid_by=None, note=None):
        receipt = self.env['ecc.receipt'].sudo().browse(receipt_id).exists()
        if not receipt:
            raise ToolError('not_found', f'No receipt with id {receipt_id}', status=404)
        try:
            receipt._telegram_update(telegram_user_id, paid_by=paid_by, note=note)
        except NotTheSender as e:
            raise ToolError('not_the_sender', 'Only the sender of the photo can answer.', status=403) from e
        return self._receipt_payload(receipt)

    @agent_tool(
        name='receipt_reply',
        title='Reply about a receipt', title_ar='رد على فاتورة',
        category='receipts', access=ACCESS_WRITE, requires=REQUIRES,
        description="""A message posted in the group as a reply to the accountant's question about a receipt
        (sent through /api/agents/telegram/reply) or to the receipt photo itself. The text is added to the
        receipt's discussion in Odoo and the question is marked answered. Error not_found: the replied message
        is not about a receipt, ignore it.""",
        params={
            'type': 'object',
            'properties': {
                'company_id': COMPANY,
                'chat_id': CHAT_ID,
                'reply_to_message_id': {'type': 'integer',
                                        'description': 'Telegram message the user replied to.'},
                'message_id': {'type': 'integer', 'description': 'Telegram message id of the reply.'},
                'sender': SENDER,
                'text': {'type': 'string', 'maxLength': 4096},
            },
            'required': ['company_id', 'chat_id', 'reply_to_message_id', 'sender', 'text'],
        },
    )
    def _tool_receipt_reply(self, company_id, chat_id, reply_to_message_id, sender, text, message_id=None):
        company = self._receipt_company(company_id)
        chat_id = str(chat_id)
        question = self.env['ecc.receipt.question'].sudo().search([
            ('chat_id', '=', chat_id), ('telegram_message_id', '=', reply_to_message_id),
            ('company_id', '=', company.id),
        ], limit=1)
        receipt = question.receipt_id or self.env['ecc.receipt.photo'].sudo().search([
            ('chat_id', '=', chat_id), ('message_id', '=', reply_to_message_id), ('company_id', '=', company.id),
        ], limit=1).receipt_id
        if not receipt:
            raise ToolError('not_found', 'The replied message is not about a receipt.', status=404)
        person = self.env['ecc.telegram.sender'].sudo()._find_or_create(
            company, sender['telegram_user_id'], sender.get('name'), sender.get('username'))
        if not person.active:
            raise ToolError('sender_ignored', 'This Telegram user is archived in Odoo: ignore the message.')
        receipt._telegram_post_reply(person, text)
        if question:
            question.write({'state': 'answered', 'answer': text, 'answered_by_id': person.id,
                            'answer_date': fields.Datetime.now()})
        return {'receipt_id': receipt.id, 'reference': receipt.name,
                'question_id': question.id or None}
