# -*- coding: utf-8 -*-
"""Agent tools of the owner cash box, called by the DoniaLink Platform: its Telegram bot (owner's private chat)
and its app (platform users to whom a manager gave the box).

Every tool (except owner_link and owner_boxes) takes the box_id and who is asking:
- ``telegram_user_id``: the bot. Only the Telegram user linked to the box may use it (error not_linked).
- ``app_user`` {"id": "dl:<platform user id>", "name"}: the DoniaLink app. The connector key is the authority:
  the platform only sends boxes it gave to that user. The name is written in the box chatter.
A refused action (amount above what is left, missing till...) returns error "refused" with a message to show
as is. Writes take an optional request_uid: the same request sent again answers what was saved (replayed);
the same request arriving twice at the same moment answers error "duplicate" (409) to the second one.
"""
import psycopg2

from odoo import api, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.donialink_agent.models.agent_registry import ACCESS_WRITE, ToolError, agent_tool

from .owner_box import OwnerNotLinked
from .owner_service import OwnerServiceError

REQUIRES = ('ecc.owner.box',)
BOX = {'type': 'integer', 'description': 'Owner cash box (see owner_boxes).'}
TG_USER = {'type': 'string', 'maxLength': 64, 'nullable': True,
           'description': 'Telegram user id of the person writing (bot).'}
APP_USER = {'type': 'object', 'nullable': True,
            'description': 'DoniaLink app user acting on the box (instead of telegram_user_id).',
            'properties': {'id': {'type': 'string', 'maxLength': 64},
                           'name': {'type': 'string', 'maxLength': 200, 'nullable': True}},
            'required': ['id']}
CARD = {'type': 'integer', 'description': 'Card shared with the box (see owner_cards).'}
AMOUNT = {'type': 'number', 'minimum': 0}
NOTE = {'type': 'string', 'maxLength': 500, 'nullable': True}
REQUEST_UID = {'type': 'string', 'maxLength': 64, 'nullable': True,
               'description': 'Unique id of this action (8-64 letters, digits, - or _): a retry never records twice.'}
PHOTOS = {'type': 'array', 'items': {'type': 'object', 'properties': {
    'content_b64': {'type': 'string'},
    'filename': {'type': 'string', 'maxLength': 200, 'nullable': True},
    'mimetype': {'type': 'string', 'maxLength': 100, 'nullable': True},
    'file_unique_id': {'type': 'string', 'maxLength': 100, 'nullable': True},
    'message_id': {'type': 'integer', 'nullable': True},
}, 'required': ['content_b64']}, 'description': 'Up to 5 photos (images, 8 MB each).'}
LIMIT = {'type': 'integer', 'minimum': 1, 'maximum': 50, 'default': 10}


def _owner_params(properties=None, required=()):
    props = {'box_id': BOX, 'telegram_user_id': TG_USER, 'app_user': APP_USER}
    props.update(properties or {})
    return {'type': 'object', 'properties': props, 'required': ['box_id', *required]}


class AgentTools(models.AbstractModel):
    _inherit = 'donialink.agent.tools'

    @api.model
    def _owner_box(self, box_id, telegram_user_id=None, app_user=None):
        """The box and the service of the channel asking (bot or DoniaLink app)."""
        box = self.env['ecc.owner.box'].sudo().browse(box_id).exists()
        if not box or not box.active:
            raise ToolError('not_found', f'No owner cash box {box_id}', status=404)
        Service = self.env['ecc.owner.service']
        if app_user:
            if not str(app_user.get('id') or '').strip():
                raise ToolError('invalid_params', "'app_user.id' is required")
            Service = Service.with_context(ecc_source='platform',
                                           ecc_actor=(app_user.get('name') or app_user['id']).strip())
        elif telegram_user_id:
            try:
                box._check_telegram_user(telegram_user_id)
            except OwnerNotLinked as e:
                raise ToolError('not_linked', 'This Telegram user is not the owner of this cash box.',
                                status=403) from e
            Service = Service.with_context(ecc_source='telegram')
        else:
            raise ToolError('invalid_params', "Give 'telegram_user_id' (bot) or 'app_user' (DoniaLink app).")
        return box.with_company(box.company_id), Service

    @api.model
    def _owner_card(self, box, **extra):
        card = box._api_card()
        card.update(extra)
        return card

    @api.model
    def _owner_run(self, func):
        try:
            # a refused or duplicate action leaves nothing half-written
            with self.env.cr.savepoint():
                return func()
        except psycopg2.IntegrityError as e:
            # two identical requests (same request_uid) at the same time: the other one saved it
            raise ToolError('duplicate', 'Already saved. Refresh to see it.', status=409) from e
        except OwnerServiceError as e:
            raise ToolError(e.code, str(e.args[0] if e.args else e),
                            status=404 if e.code == 'not_found' else 422) from e
        except AccessError as e:
            raise ToolError('forbidden', str(e.args[0] if e.args else e), status=403) from e
        except UserError as e:
            raise ToolError('refused', str(e.args[0] if e.args else e)) from e

    @api.model
    def _owner_flat(self, Service, result, ok_icon='✅'):
        """Box tools answer the balance card at the top level (bot contract) plus the other keys."""
        result = dict(result)
        flat = dict(result.pop('card'))
        flat.update(result)
        if Service.env.context.get('ecc_source') == 'telegram' and ok_icon and not result.get('replayed'):
            flat['text'] = '%s %s' % (ok_icon, flat.get('text') or '')
        return flat

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
        description="""With telegram_user_id: the cash boxes linked to this Telegram user (an owner may have one
        per café / company). Without it: every active cash box of the companies of this connector, for a
        DoniaLink manager to give boxes to app users (on_platform tells which are on the DoniaLink app).""",
        params={'type': 'object', 'properties': {'telegram_user_id': TG_USER}},
    )
    def _tool_owner_boxes(self, telegram_user_id=None):
        Box = self.env['ecc.owner.box'].sudo()
        if telegram_user_id:
            boxes = Box.search([('telegram_user_id', '=', str(telegram_user_id))])
        else:
            boxes = Box.search([('company_id', 'in', self.env.user.company_ids.ids)])
        return {'boxes': [self._owner_card(box.with_company(box.company_id), on_platform=box.platform_enabled)
                          for box in boxes]}

    @agent_tool(
        name='owner_platform_link', title='Box on the DoniaLink app', title_ar='الصندوق على تطبيق دونيا لينك',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The platform gave the box to at least one DoniaLink app user (enabled true) or took it
        back from the last one (false). Odoo then sends the box notifications (kind session_closed, statement,
        card_move...) to /api/agents/telegram/owner even without a Telegram link (telegram_user_id null).""",
        params={'type': 'object', 'properties': {'box_id': BOX, 'enabled': {'type': 'boolean'}},
                'required': ['box_id', 'enabled']},
    )
    def _tool_owner_platform_link(self, box_id, enabled):
        box = self.env['ecc.owner.box'].sudo().browse(box_id).exists()
        if not box:
            raise ToolError('not_found', f'No owner cash box {box_id}', status=404)
        if box.platform_enabled != enabled:
            box.platform_enabled = enabled
        return {'box_id': box.id, 'on_platform': box.platform_enabled}

    @agent_tool(
        name='owner_card', title='Owner balance card', title_ar='رصيد المالك',
        category='owner', requires=REQUIRES,
        description="""Balance card of the owner's cash box: balance (negative = the business owes him),
        closed POS sessions not collected yet, the cards shared with the box (cards) and a ready text ("Your
        cash box: 3,400,000 IQD · 2 closed sessions not collected").""",
        params=_owner_params(),
    )
    def _tool_owner_card(self, box_id, telegram_user_id=None, app_user=None):
        box, _service = self._owner_box(box_id, telegram_user_id, app_user)
        return self._owner_card(box)

    @agent_tool(
        name='owner_sessions', title='Sessions to collect', title_ar='جلسات للاستلام',
        category='owner', requires=REQUIRES,
        description="""Closed POS sessions whose cash the owner has not collected yet, newest first, with the
        cash left to collect.""",
        params=_owner_params({'limit': LIMIT}),
    )
    def _tool_owner_sessions(self, box_id, telegram_user_id=None, app_user=None, limit=10):
        box, _service = self._owner_box(box_id, telegram_user_id, app_user)
        return {'sessions': box._api_sessions(limit)}

    @agent_tool(
        name='owner_collect', title='Collect session cash', title_ar='استلام نقد الجلسة',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The owner took the cash of a closed POS session: amount omitted = all that is left
        ("Yes, all"); a smaller amount ("Other amount") opens a difference for the accountant. A session is
        collected once; the total cannot exceed its cash (error refused). Returns the new balance card, the
        sessions left and text ("Collected 1,250,000 from POS/00412").""",
        params=_owner_params({'session_id': {'type': 'integer'}, 'amount': dict(AMOUNT, nullable=True),
                              'request_uid': REQUEST_UID}, required=('session_id',)),
    )
    def _tool_owner_collect(self, box_id, session_id, telegram_user_id=None, app_user=None, amount=None,
                            request_uid=None):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        result = self._owner_run(lambda: service.collect(box, session_id, amount, request_uid))
        return self._owner_flat(service, result)

    @agent_tool(
        name='owner_categories', title='Owner expense categories', title_ar='فئات مصاريف المالك',
        category='owner', requires=REQUIRES,
        description="""Categories offered as buttons when the owner records an expense (Generator, Rent,
        Supplier, Salaries, Repairs, Other...).""",
        params=_owner_params(),
    )
    def _tool_owner_categories(self, box_id, telegram_user_id=None, app_user=None):
        box, _service = self._owner_box(box_id, telegram_user_id, app_user)
        return {'categories': box._api_categories()}

    @agent_tool(
        name='owner_expense', title='Owner expense', title_ar='مصروف المالك',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The owner paid a business expense from his cash: photo(s), amount, category (from
        owner_categories) and an optional note. Lowers his balance at once; the accountant reviews it in the
        Receipts inbox. Returns the card, receipt_id, reference and text ("Expense 75,000 recorded · waiting
        for accountant review").""",
        params=_owner_params({
            'amount': AMOUNT,
            'category_id': {'type': 'integer'},
            'note': NOTE,
            'chat_id': {'type': 'string', 'maxLength': 64, 'nullable': True},
            'message_id': {'type': 'integer', 'nullable': True},
            'photos': PHOTOS,
            'request_uid': REQUEST_UID,
        }, required=('amount', 'category_id')),
    )
    def _tool_owner_expense(self, box_id, amount, category_id, telegram_user_id=None, app_user=None, note=None,
                            chat_id=None, message_id=None, photos=(), request_uid=None):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        telegram = {}
        if not app_user:
            telegram = {'chat_id': chat_id, 'message_id': message_id,
                        'sender': self.env['ecc.telegram.sender'].sudo()._find_or_create(
                            box.company_id, telegram_user_id, box.telegram_name or box.name)}
        result = self._owner_run(lambda: service.expense(box, amount, category_id, note, photos, request_uid,
                                                         **telegram))
        return self._owner_flat(service, result)

    @agent_tool(
        name='owner_took', title='Took for me', title_ar='سحب شخصي',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The owner took cash for himself (personal withdrawal): recorded as Owner Drawings
        (equity), never as an expense. Returns the card and text.""",
        params=_owner_params({'amount': AMOUNT, 'note': NOTE, 'request_uid': REQUEST_UID}, required=('amount',)),
    )
    def _tool_owner_took(self, box_id, amount, telegram_user_id=None, app_user=None, note=None, request_uid=None):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        result = self._owner_run(lambda: service.took(box, amount, note, request_uid))
        return self._owner_flat(service, result)

    @agent_tool(
        name='owner_deposit', title='Owner deposit', title_ar='إيداع المالك',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The owner deposited cash: target "bank", "till" (back to the POS cash drawer; only when
        till_available) or "card" (on a card shared with the box: card_id, see owner_cards; the answer then
        has bank_card). Returns the card and text.""",
        params=_owner_params({'amount': AMOUNT, 'target': {'type': 'string', 'enum': ['bank', 'till', 'card']},
                              'card_id': dict(CARD, nullable=True), 'note': NOTE, 'request_uid': REQUEST_UID},
                             required=('amount', 'target')),
    )
    def _tool_owner_deposit(self, box_id, amount, target, telegram_user_id=None, app_user=None, card_id=None,
                            note=None, request_uid=None):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        result = self._owner_run(lambda: service.deposit(box, amount, target, note, request_uid, card_id))
        return self._owner_flat(service, result)

    @agent_tool(
        name='owner_moves', title='Last moves', title_ar='آخر الحركات',
        category='owner', requires=REQUIRES,
        description="""Last movements of the owner's cash box with the running balance, newest first.""",
        params=_owner_params({'limit': LIMIT}),
    )
    def _tool_owner_moves(self, box_id, telegram_user_id=None, app_user=None, limit=10):
        box, _service = self._owner_box(box_id, telegram_user_id, app_user)
        rows, lines = box._api_moves(limit)
        return {'moves': rows, 'balance': box.balance, 'text': '\n'.join(lines) or 'No movements yet.'}

    @agent_tool(
        name='owner_count', title='Count my cash', title_ar='عد نقدي',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The owner counted the cash he holds. A difference with the computed balance goes to the
        accountant to explain. Returns difference (counted − balance), expected and a text.""",
        params=_owner_params({'counted': {'type': 'number'}}, required=('counted',)),
    )
    def _tool_owner_count(self, box_id, counted, telegram_user_id=None, app_user=None):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        result = self._owner_run(lambda: service.count(box, counted))
        return self._owner_flat(service, result, ok_icon='⚠️' if result.get('difference') else '✅')

    @agent_tool(
        name='owner_notifications', title='Owner notification settings', title_ar='إعدادات إشعارات المالك',
        category='owner', requires=REQUIRES,
        description="""What the owner of the box is told: notifications {session_closed (session closed, cash to
        collect), reminder_expense (daily reminder to record cash expenses when nothing was recorded),
        reminder_count_weekday ('0' Monday … '6' Sunday, null = never: weekly reminder to count the cash),
        reminder_hour (0-23, owner's time)}.""",
        params=_owner_params({}),
    )
    def _tool_owner_notifications(self, box_id, telegram_user_id=None, app_user=None):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        return service.notifications(box)

    @agent_tool(
        name='owner_notifications_set', title='Change owner notifications', title_ar='تغيير إشعارات المالك',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""Turn the owner's notifications on or off (see owner_notifications). Only the values given
        change. reminder_count_weekday null = never. Returns the new notifications and a text.""",
        params=_owner_params({
            'session_closed': {'type': 'boolean'},
            'reminder_expense': {'type': 'boolean'},
            'reminder_count_weekday': {'type': 'string', 'enum': ['0', '1', '2', '3', '4', '5', '6'],
                                       'nullable': True},
            'reminder_hour': {'type': 'integer', 'minimum': 0, 'maximum': 23},
        }),
    )
    def _tool_owner_notifications_set(self, box_id, telegram_user_id=None, app_user=None, session_closed=None,
                                      reminder_expense=None, reminder_count_weekday=False, reminder_hour=None):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        return self._owner_run(lambda: service.set_notifications(
            box, session_closed=session_closed, reminder_expense=reminder_expense,
            reminder_count_weekday=reminder_count_weekday, reminder_hour=reminder_hour))

    @agent_tool(
        name='owner_statements', title='Owner statements', title_ar='كشوفات المالك',
        category='owner', requires=REQUIRES,
        description="""Last statements of the cash box, newest first: period, opening, collected, from_card,
        spent, took, deposited, adjusted, closing, state (sent = waiting for the owner's answer, see
        owner_statement_answer) and text.""",
        params=_owner_params({'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'default': 12}}),
    )
    def _tool_owner_statements(self, box_id, telegram_user_id=None, app_user=None, limit=12):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        return service.statements(box, limit)

    @agent_tool(
        name='owner_statement_answer', title='Statement answer', title_ar='رد على الكشف',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""Answer of the owner to a statement sent by Odoo (kind "statement", data.statement_id):
        correct true (✅ Correct) or false (⚠️ Not correct, opens a difference for the accountant), with an
        optional note. Error refused when it was already answered.""",
        params=_owner_params({'statement_id': {'type': 'integer'}, 'correct': {'type': 'boolean'}, 'note': NOTE},
                             required=('statement_id', 'correct')),
    )
    def _tool_owner_statement_answer(self, box_id, statement_id, correct, telegram_user_id=None, app_user=None,
                                     note=None):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        result = self._owner_run(lambda: service.statement_answer(box, statement_id, correct, note))
        return self._owner_flat(service, result, ok_icon='✅' if correct else '⚠️')

    # ------------------------------------------------------------------
    # Cards: the bank accounts the POS card terminal pays into, shared with chosen boxes
    # ------------------------------------------------------------------

    @agent_tool(
        name='owner_cards', title='Owner cards', title_ar='بطاقات المالك',
        category='owner', requires=REQUIRES,
        description="""Cards shared with the box: card_id, name, bank, account and balance (the balance of the
        card's account in the books). Only these cards may be used with this box.""",
        params=_owner_params(),
    )
    def _tool_owner_cards(self, box_id, telegram_user_id=None, app_user=None):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        return service.cards(box)

    @agent_tool(
        name='owner_card_home', title='Card balance and history', title_ar='رصيد البطاقة وحركاتها',
        category='owner', requires=REQUIRES,
        description="""A card shared with the box: bank_card (balance), moves (journal items of the card's
        account, newest first: type sales | withdraw | drawing | expense | deposit | adjust | bank, owner,
        amount, balance_after, review) and the box card. Error forbidden for a card not shared with the box.""",
        params=_owner_params({'card_id': CARD, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100,
                                                         'default': 30}}, required=('card_id',)),
    )
    def _tool_owner_card_home(self, box_id, card_id, telegram_user_id=None, app_user=None, limit=30):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        return self._owner_run(lambda: service.card_home(box, card_id, limit))

    @agent_tool(
        name='owner_card_withdraw', title='Withdraw from a card', title_ar='سحب نقد من البطاقة',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""Cash taken from a card: target "box" (into the owner's cash box: his balance goes up) or
        "took" (for himself, Owner Drawings). Returns bank_card, card (box) and text.""",
        params=_owner_params({'card_id': CARD, 'amount': AMOUNT,
                              'target': {'type': 'string', 'enum': ['box', 'took'], 'default': 'box'},
                              'note': NOTE, 'request_uid': REQUEST_UID}, required=('card_id', 'amount')),
    )
    def _tool_owner_card_withdraw(self, box_id, card_id, amount, telegram_user_id=None, app_user=None,
                                  target='box', note=None, request_uid=None):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        return self._owner_run(lambda: service.card_withdraw(box, card_id, amount, target, note, request_uid))

    @agent_tool(
        name='owner_card_expense', title='Pay by card', title_ar='دفع بالبطاقة',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""An expense paid with a card: amount, category (owner_categories), note, photos. Lowers
        the card balance at once; the accountant reviews it in the Receipts inbox (rejected = back on the
        card). Returns bank_card, card (box), receipt_id, reference and text.""",
        params=_owner_params({'card_id': CARD, 'amount': AMOUNT, 'category_id': {'type': 'integer'}, 'note': NOTE,
                              'photos': PHOTOS, 'request_uid': REQUEST_UID},
                             required=('card_id', 'amount', 'category_id')),
    )
    def _tool_owner_card_expense(self, box_id, card_id, amount, category_id, telegram_user_id=None, app_user=None,
                                 note=None, photos=(), request_uid=None):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        return self._owner_run(lambda: service.card_expense(box, card_id, amount, category_id, note, photos,
                                                            request_uid))

    @agent_tool(
        name='owner_card_count', title='Check card balance', title_ar='مطابقة رصيد البطاقة',
        category='owner', access=ACCESS_WRITE, requires=REQUIRES,
        description="""The owner checked the card balance in the bank app (counted). A difference with the books
        goes to the accountant to explain. Returns difference (counted − books), expected, bank_card and text.""",
        params=_owner_params({'card_id': CARD, 'counted': {'type': 'number'}}, required=('card_id', 'counted')),
    )
    def _tool_owner_card_count(self, box_id, card_id, counted, telegram_user_id=None, app_user=None):
        box, service = self._owner_box(box_id, telegram_user_id, app_user)
        return self._owner_run(lambda: service.card_count(box, card_id, counted))
