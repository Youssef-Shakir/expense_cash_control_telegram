# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class OwnerAppAccess(models.TransientModel):
    """The accountant gives the owner a login for the owner app: a new portal user (free) or an existing user."""
    _name = 'ecc.owner.app.access'
    _description = 'Owner App Access'

    box_id = fields.Many2one('ecc.owner.box', required=True, readonly=True,
                             default=lambda self: self.env.context.get('ecc_owner_box_id'))
    mode = fields.Selection([('new', 'Create a new login'), ('existing', 'Use an existing user')],
                            default='new', required=True)
    user_id = fields.Many2one('res.users', string='User')
    name = fields.Char('Name', default=lambda self: self._default_name())
    login = fields.Char('Login', help='Phone number or e-mail the owner types to log in.')
    password = fields.Char('Password')
    lang = fields.Selection(selection='_lang_selection', string='App Language', default=lambda self: self._default_lang())
    app_url = fields.Char(related='box_id.app_url')

    @api.model
    def _lang_selection(self):
        return self.env['res.lang'].get_installed()

    @api.model
    def _default_lang(self):
        codes = [code for code, _name in self.env['res.lang'].get_installed()]
        arabic = [code for code in codes if code.startswith('ar')]
        return arabic[0] if arabic else self.env.user.lang

    @api.model
    def _default_name(self):
        box = self.env['ecc.owner.box'].browse(self.env.context.get('ecc_owner_box_id')).exists()
        return box.name or False

    def action_confirm(self):
        self.ensure_one()
        box = self.box_id
        if self.mode == 'existing':
            if not self.user_id:
                raise UserError(_('Choose the user.'))
            user = self.user_id
        else:
            login = (self.login or '').strip()
            if not login or not self.password:
                raise UserError(_('Login and password are required.'))
            if self.env['res.users'].sudo().with_context(active_test=False).search_count([('login', '=', login)]):
                raise UserError(_('The login "%s" is already used: choose "Use an existing user".', login))
            user = self.env['res.users'].sudo().with_context(no_reset_password=True).create({
                'name': self.name or box.name,
                'login': login,
                'password': self.password,
                'lang': self.lang or self.env.user.lang,
                'company_id': box.company_id.id,
                'company_ids': [(6, 0, box.company_id.ids)],
                'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
            })
        box.app_user_id = user
        box.message_post(body=_('Owner app access given to %(user)s (login %(login)s). App: %(url)s',
                                user=user.name, login=user.login, url=box.app_url))
        return {'type': 'ir.actions.act_window_close'}
