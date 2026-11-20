# -*- coding: utf-8 -*-
"""Calls to the owner cash box service the way the DoniaLink App does, for the tests.

``owner_call(env, box, 'collect', session_id=...)`` runs the action in a savepoint and answers like the app:
box actions return the balance card at the top level plus the other keys. A refusal raises ``CallError`` with
the code the app shows (refused, not_found, forbidden, duplicate...).
"""
import psycopg2

from odoo.exceptions import AccessError, UserError

from odoo.addons.expense_cash_control_telegram.models.owner_service import OwnerServiceError

FLAT = {'collect', 'expense', 'took', 'deposit', 'count', 'statement_answer'}


class CallError(Exception):

    def __init__(self, code, message='', status=422):
        super().__init__(message)
        self.code = code
        self.status = status


def _actions(service, box, p):
    return {
        'card': lambda: {'card': box._api_card()},
        'sessions': lambda: {'sessions': box._api_sessions(p.get('limit', 10))},
        'categories': lambda: {'categories': box._api_categories()},
        'collect': lambda: service.collect(box, p['session_id'], p.get('amount'), p.get('request_uid')),
        'expense': lambda: service.expense(box, p['amount'], p['category_id'], p.get('note'), p.get('photos', ()),
                                           p.get('request_uid')),
        'took': lambda: service.took(box, p['amount'], p.get('note'), p.get('request_uid')),
        'deposit': lambda: service.deposit(box, p['amount'], p['target'], p.get('note'), p.get('request_uid'),
                                           p.get('card_id')),
        'moves': lambda: dict(zip(('moves', 'lines'), box._api_moves(p.get('limit', 10)))),
        'count': lambda: service.count(box, p['counted']),
        'notifications': lambda: service.notifications(box),
        'notifications_set': lambda: service.set_notifications(
            box, session_closed=p.get('session_closed'), reminder_expense=p.get('reminder_expense'),
            reminder_count_weekday=p.get('reminder_count_weekday', False), reminder_hour=p.get('reminder_hour')),
        'statements': lambda: service.statements(box, p.get('limit', 12)),
        'statement_answer': lambda: service.statement_answer(box, p['statement_id'], p['correct'], p.get('note')),
        'cards': lambda: service.cards(box),
        'card_home': lambda: service.card_home(box, p['card_id'], p.get('limit', 30)),
        'card_withdraw': lambda: service.card_withdraw(box, p['card_id'], p['amount'], p.get('target', 'box'),
                                                       p.get('note'), p.get('request_uid')),
        'card_expense': lambda: service.card_expense(box, p['card_id'], p['amount'], p['category_id'],
                                                     p.get('note'), p.get('photos', ()), p.get('request_uid')),
        'card_count': lambda: service.card_count(box, p['card_id'], p['counted']),
    }


def owner_call(env, box, name, actor=None, **params):
    box = box.sudo().with_company(box.company_id)
    context = {'ecc_source': 'app'}
    if actor:
        context['ecc_actor'] = actor
    service = env['ecc.owner.service'].with_context(**context)
    try:
        with env.cr.savepoint():
            result = _actions(service, box, params)[name]()
    except psycopg2.IntegrityError as e:
        raise CallError('duplicate', 'Already saved.', 409) from e
    except OwnerServiceError as e:
        raise CallError(e.code, str(e.args[0] if e.args else e), 404 if e.code == 'not_found' else 422) from e
    except AccessError as e:
        raise CallError('forbidden', str(e.args[0] if e.args else e), 403) from e
    except UserError as e:
        raise CallError('refused', str(e.args[0] if e.args else e)) from e
    if name in FLAT:
        result = dict(result)
        flat = dict(result.pop('card'))
        flat.update(result)
        return flat
    return result
