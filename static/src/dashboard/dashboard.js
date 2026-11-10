/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ExpenseCashDashboard } from "@expense_cash_control/dashboard/dashboard";

patch(ExpenseCashDashboard.prototype, {
    openOwnerBox(id) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "ecc.owner.box",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    },
});
