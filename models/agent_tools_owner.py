# -*- coding: utf-8 -*-
"""Agent tools of the owner cash box, called by the DoniaLink Platform's bot in the owner's private chat.

Every tool (except owner_link and owner_boxes) takes the box_id and the telegram_user_id of the person
writing: only the owner linked to the box may use it (error not_linked). A refused action (amount above what
is left, missing till...) returns error "refused" with a message to show the owner as is.
"""
import base64
import binascii

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.donialink_agent.models.agent_registry import ACCESS_WRITE, ToolError, agent_tool

from .owner_box import OwnerNotLinked

REQUIRES = ('ecc.owner.box',)
BOX = {'type': 'integer', 'description': 'Owner cash box (see owner_boxes).'}
TG_USER = {'type': 'string', 'maxLength': 64, 'description': 'Telegram user id of the person writing.'}
AMOUNT = {'type': 'number', 'minimum': 0}
NOTE = {'type': 'string', 'maxLength': 500, 'nullable': True}


def _owner_params(properties=None, required=()):
    props = {'box_id': BOX, 'telegram_user_id': TG_USER}
    props.update(properties or {})
    return {'type': 'object', 'properties': props, 'required': ['box_id', 'telegram_user_id', *required]}


class AgentTools(models.AbstractModel):
    _inherit = 'donialink.agent.tools'

    @api.model
    def _owner_box(self, box_id, telegram_user_id):
        box = self.env['ecc.owner.box'].sudo().browse(box_id).exists()
        if not box:
            raise ToolError('not_found', f'No owner cash box {box_id}', status=404)
        try:
            box._check_telegram_user(telegram_user_id)
        except OwnerNotLinked as e:
            raise ToolError('not_linked', 'This Telegram user is not the owner of this cash box.', status=403) from e
        return box.with_company(box.company_id)

    @api.model
    def _owner_card(self, box, **extra):
        card = box._api_card()
        card.update(extra)
        return card

    @api.model
    def _owner_run(self, func):
        try:
            return func()
        except UserError as e:
            raise ToolError('refused', str(e.args[0] if e.args else e)) from e

    # ------------------------------------------------------------------

    @agent_tool(
        name='owner_link', title='Link an owner', title_ar='ربط المالك',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The owner opened the bot with the link code of his cash box (created in Odoo with
        "Telegram link", t.me/<bot>?start=<code>). Links his Telegram user to the box and returns his balance
        card. Error invalid_code: unknown or already used code.""",
        params={'type': 'object', 'properties': {
            'code': {'type': 'string', 'maxLength': 32},
            'telegram_user_id': TG_USER,
            'name': {'type': 'string', 'maxLength': 200, 'nullable': True},
        }, 'required': ['code', 'telegram_user_id']},
    )
    def _tool_owner_link(self, code, telegram_user_id, name=None):
        box = self.env['ecc.owner.box'].sudo().search([('link_code', '=', code.strip().upper())], limit=1)
        if not box:
            raise ToolError('invalid_code', 'Unknown or already used link code.', status=404)
        box._telegram_link(telegram_user_id, name)
        return self._owner_card(box.with_company(box.company_id))

    @agent_tool(
        name='owner_boxes', title='Owner cash boxes', title_ar='صناديق المالك',
        category='owner', requires=REQUIRES,
        description="""Cash boxes linked to this Telegram user (an owner may have one per café / company).""",
        params={'type': 'object', 'properties': {'telegram_user_id': TG_USER}, 'required': ['telegram_user_id']},
    )
    def _tool_owner_boxes(self, telegram_user_id):
        boxes = self.env['ecc.owner.box'].sudo().search([('telegram_user_id', '=', str(telegram_user_id))])
        return {'boxes': [self._owner_card(box.with_company(box.company_id)) for box in boxes]}

    @agent_tool(
        name='owner_card', title='Owner balance card', title_ar='رصيد المالك',
        category='owner', requires=REQUIRES,
        description="""Balance card of the owner's cash box: balance (negative = the business owes him),
        closed POS sessions not collected yet, and a ready text ("Your cash box: 3,400,000 IQD · 2 closed
        sessions not collected").""",
        params=_owner_params(),
    )
    def _tool_owner_card(self, box_id, telegram_user_id):
        return self._owner_card(self._owner_box(box_id, telegram_user_id))

    @agent_tool(
        name='owner_sessions', title='Sessions to collect', title_ar='جلسات للاستلام',
        category='owner', requires=REQUIRES,
        description="""Closed POS sessions whose cash the owner has not collected yet, newest first, with the
        cash left to collect.""",
        params=_owner_params({'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'default': 10}}),
    )
    def _tool_owner_sessions(self, box_id, telegram_user_id, limit=10):
        box = self._owner_box(box_id, telegram_user_id)
        sessions = box._api_sessions(limit)
        return {'sessions': sessions}

    @agent_tool(
        name='owner_collect', title='Collect session cash', title_ar='استلام نقد الجلسة',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The owner took the cash of a closed POS session: amount omitted = all that is left
        ("Yes, all"); a smaller amount ("Other amount") opens a difference for the accountant. A session is
        collected once; the total cannot exceed its cash (error refused). Returns the new balance card and
        text ("Collected 1,250,000 from POS/00412 · New balance 4,650,000").""",
        params=_owner_params({'session_id': {'type': 'integer'},
                              'amount': dict(AMOUNT, nullable=True)}, required=('session_id',)),
    )
    def _tool_owner_collect(self, box_id, telegram_user_id, session_id, amount=None):
        box = self._owner_box(box_id, telegram_user_id)
        session = self.env['pos.session'].sudo().browse(session_id).exists()
        if not session:
            raise ToolError('not_found', f'No POS session {session_id}', status=404)
        move = self._owner_run(lambda: box._collect_session(session, amount))
        card = self._owner_card(box)
        card['text'] = '✅ Collected %s from %s · New balance %s' % (
            box.currency_id.format(move.amount), session.name, card['balance_text'])
        return card

    @agent_tool(
        name='owner_categories', title='Owner expense categories', title_ar='فئات مصاريف المالك',
        category='owner', requires=REQUIRES,
        description="""Categories offered as buttons when the owner records an expense (Generator, Rent,
        Supplier, Salaries, Repairs, Other...).""",
        params=_owner_params(),
    )
    def _tool_owner_categories(self, box_id, telegram_user_id):
        box = self._owner_box(box_id, telegram_user_id)
        return {'categories': box._api_categories()}

    @agent_tool(
        name='owner_expense', title='Owner expense', title_ar='مصروف المالك',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The owner paid a business expense from his cash: photo(s), amount, category (from
        owner_categories) and an optional note. Lowers his balance at once; the accountant reviews it in the
        Receipts inbox. Returns the card and text ("Expense 75,000 recorded · New balance ... · waiting for
        accountant review").""",
        params=_owner_params({
            'amount': AMOUNT,
            'category_id': {'type': 'integer'},
            'note': NOTE,
            'chat_id': {'type': 'string', 'maxLength': 64, 'nullable': True},
            'message_id': {'type': 'integer', 'nullable': True},
            'photos': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'content_b64': {'type': 'string'},
                'filename': {'type': 'string', 'maxLength': 200, 'nullable': True},
                'mimetype': {'type': 'string', 'maxLength': 100, 'nullable': True},
                'file_unique_id': {'type': 'string', 'maxLength': 100, 'nullable': True},
                'message_id': {'type': 'integer', 'nullable': True},
            }, 'required': ['content_b64']}},
        }, required=('amount', 'category_id')),
    )
    def _tool_owner_expense(self, box_id, telegram_user_id, amount, category_id, note=None, chat_id=None,
                            message_id=None, photos=()):
        box = self._owner_box(box_id, telegram_user_id)
        category = box._api_category(category_id)
        if not category:
            raise ToolError('not_found', f'No category {category_id}', status=404)
        decoded = []
        for photo in photos or ():
            try:
                content = base64.b64decode(photo['content_b64'], validate=True)
            except (binascii.Error, ValueError) as e:
                raise ToolError('invalid_photo', 'A photo is not valid base64.') from e
            decoded.append(dict(photo, content=content))
        sender = self.env['ecc.telegram.sender'].sudo()._find_or_create(
            box.company_id, telegram_user_id, box.telegram_name or box.name)
        move, receipt = self._owner_run(lambda: box._record_expense(
            amount, category, note=note, photos=decoded, chat_id=chat_id, message_id=message_id, sender=sender))
        card = self._owner_card(box, receipt_id=receipt.id, reference=receipt.name)
        card['text'] = '✅ Expense %s (%s) recorded · New balance %s · waiting for accountant review' % (
            box.currency_id.format(-move.amount), category.name, card['balance_text'])
        return card

    @agent_tool(
        name='owner_took', title='Took for me', title_ar='سحب شخصي',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The owner took cash for himself (personal withdrawal): recorded as Owner Drawings
        (equity), never as an expense. Returns the card and text.""",
        params=_owner_params({'amount': AMOUNT, 'note': NOTE}, required=('amount',)),
    )
    def _tool_owner_took(self, box_id, telegram_user_id, amount, note=None):
        box = self._owner_box(box_id, telegram_user_id)
        move = self._owner_run(lambda: box._record_drawing(amount, note))
        card = self._owner_card(box)
        card['text'] = '✅ Took %s for you · New balance %s' % (
            box.currency_id.format(-move.amount), card['balance_text'])
        return card

    @agent_tool(
        name='owner_deposit', title='Owner deposit', title_ar='إيداع المالك',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The owner deposited cash: target "bank" or "till" (back to the POS cash drawer; only
        when till_available). Returns the card and text.""",
        params=_owner_params({'amount': AMOUNT, 'target': {'type': 'string', 'enum': ['bank', 'till']},
                              'note': NOTE}, required=('amount', 'target')),
    )
    def _tool_owner_deposit(self, box_id, telegram_user_id, amount, target, note=None):
        box = self._owner_box(box_id, telegram_user_id)
        move = self._owner_run(lambda: box._record_deposit(amount, target, note))
        card = self._owner_card(box)
        card['text'] = '✅ Deposited %s to the %s · New balance %s' % (
            box.currency_id.format(-move.amount), 'bank' if target == 'bank' else 'till', card['balance_text'])
        return card

    @agent_tool(
        name='owner_moves', title='Last moves', title_ar='آخر الحركات',
        category='owner', requires=REQUIRES,
        description="""Last movements of the owner's cash box with the running balance, newest first.""",
        params=_owner_params({'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'default': 10}}),
    )
    def _tool_owner_moves(self, box_id, telegram_user_id, limit=10):
        box = self._owner_box(box_id, telegram_user_id)
        rows, lines = box._api_moves(limit)
        return {'moves': rows, 'balance': box.balance, 'text': '\n'.join(lines) or 'No movements yet.'}

    @agent_tool(
        name='owner_count', title='Count my cash', title_ar='عد نقدي',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The owner counted the cash he holds. A difference with the computed balance goes to the
        accountant to explain. Returns difference (counted − balance) and a text.""",
        params=_owner_params({'counted': {'type': 'number'}}, required=('counted',)),
    )
    def _tool_owner_count(self, box_id, telegram_user_id, counted):
        box = self._owner_box(box_id, telegram_user_id)
        expected = box.balance
        difference = box._record_count(counted)
        fmt = box.currency_id.format
        if difference:
            text = '⚠️ You counted %s, the books say %s (difference %s). The accountant will check it.' % (
                fmt(counted), fmt(expected), fmt(difference.amount))
        else:
            text = '✅ %s — it matches the books.' % fmt(counted)
        return self._owner_card(box, difference=difference.amount if difference else 0.0, text=text)

    @agent_tool(
        name='owner_statement_answer', title='Statement answer', title_ar='رد على الكشف',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""Answer of the owner to a statement sent by Odoo (kind "statement", data.statement_id):
        correct true (✅ Correct) or false (⚠️ Not correct, opens a difference for the accountant), with an
        optional note.""",
        params=_owner_params({'statement_id': {'type': 'integer'}, 'correct': {'type': 'boolean'}, 'note': NOTE},
                             required=('statement_id', 'correct')),
    )
    def _tool_owner_statement_answer(self, box_id, telegram_user_id, statement_id, correct, note=None):
        box = self._owner_box(box_id, telegram_user_id)
        statement = self.env['ecc.owner.statement'].sudo().browse(statement_id).exists()
        if not statement or statement.box_id != box:
            raise ToolError('not_found', f'No statement {statement_id} for this box', status=404)
        statement._answer(correct, note)
        text = '✅ Thank you, statement confirmed.' if correct else \
            '⚠️ Noted. The accountant will check the statement with you.'
        return self._owner_card(box, statement_state=statement.state, text=text)
