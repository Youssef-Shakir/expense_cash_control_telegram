# -*- coding: utf-8 -*-
"""Owner cash box notifications also land in the DoniaLink App inbox: the owner's (a tap opens the cash box
screen) and the people chosen for each kind in DoniaLink App > Kinds. (Was part of donialink_app_telegram.)"""
from datetime import timedelta

from odoo import fields, models

OWNER_PREFIX = 'owner_'
ORIGIN = 'owner_cash_box'


class OwnerBox(models.Model):
    _inherit = 'ecc.owner.box'

    def _owner_notify(self, kind, text, title, body=None, route='home', card=None, tag=None, data=None,
                      raise_errors=False):
        """Also into the DoniaLink App: to the owner's app login and to the people chosen for the kind."""
        answer, pushed = super()._owner_notify(kind, text, title, body=body, route=route, card=card, tag=tag,
                                               data=data, raise_errors=raise_errors)
        box = self.sudo()
        Message = self.env['donialink.app.message']
        code = OWNER_PREFIX + kind
        kind_rec = self.env['donialink.app.kind']._get(code)
        # one event (a card movement told to every co-owner, a session of a POS shared by several boxes) reaches
        # each person once: the tag names the event
        origin = '%s:%s' % (ORIGIN, tag) if tag else ORIGIN
        told = self._dl_app_told(kind_rec, origin) if tag else self.env['res.users']
        values = dict(title=title, origin=origin, add_recipients=False, fallback_kind=None)
        mine = Message.browse()
        owner = box.app_user_id - told
        if owner:
            # the owner's own box, whatever the companies of their login. Their phones were already notified by
            # _app_push (same login, same phones): inbox only
            mine = Message._dl_from_telegram(code, body or text, box.company_id, users=owner,
                                             url=box._dl_app_hash(route, card), push=False,
                                             company_filter=False, **values)
        others = Message.browse()
        if kind_rec and kind_rec.active:
            users = kind_rec._recipients(box.company_id) - box.app_user_id - told
            others = Message._dl_from_telegram(code, body or text, box.company_id, users=users, **values)
        # delivered: the OWNER has it (a statement then waits for their answer); the others are only told
        if (mine or box.app_user_id & told) and not (answer or {}).get('delivered'):
            answer = dict(answer or {}, delivered=True, app_messages=len(mine | others))
        return answer, pushed

    def _dl_app_told(self, kind, origin):
        """The people who got this event in their app inbox in the last minutes (the same event told to several
        boxes; a statement sent again later reaches them again)."""
        if not kind:
            return self.env['res.users']
        since = fields.Datetime.now() - timedelta(minutes=10)
        return self.env['donialink.app.message'].sudo().search(
            [('kind_id', '=', kind.id), ('origin', '=', origin), ('create_date', '>=', since)]).user_id
