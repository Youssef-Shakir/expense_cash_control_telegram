# -*- coding: utf-8 -*-
"""donialink_app_receipts (receipts from the DoniaLink App) and the owner cash box part of donialink_app_telegram
were folded into this module. Their records (the field ecc.receipt.app_user_id and its data, the group "Can Send
Receipts", the "Send receipt" screen, the kinds, the views) get the same XML id in this module, so they stay when
the old modules are uninstalled: Odoo keeps a record that another module still names. The "extends model X"
markers (ir.model) are not copied: the modules that define the models have their own."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        INSERT INTO ir_model_data (module, name, model, res_id, noupdate, create_uid, create_date, write_uid,
                                   write_date)
        SELECT 'expense_cash_control_telegram', old.name, old.model, old.res_id, old.noupdate, old.create_uid,
               old.create_date, old.write_uid, now() AT TIME ZONE 'UTC'
          FROM ir_model_data old
         WHERE old.model != 'ir.model'
           AND (old.module = 'donialink_app_receipts'
                OR (old.module = 'donialink_app_telegram' AND old.name LIKE %s))
           AND NOT EXISTS (SELECT 1 FROM ir_model_data new
                            WHERE new.module = 'expense_cash_control_telegram' AND new.name = old.name)
    """, ['kind\\_owner\\_%'])
    _logger.info('expense_cash_control_telegram: %s records taken over from donialink_app_receipts and '
                 'donialink_app_telegram', cr.rowcount)
