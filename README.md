# Expenses & Cash Control – Telegram Receipts | استلام الفواتير عبر تيليجرام

Odoo 18 · Developed by **Yousif Shakir** · [donialink.com](https://www.donialink.com)

Client staff post bill photos in their Telegram group. The **DoniaLink bot** (run by the DoniaLink
Platform) asks *who paid?* and *any note?*, then sends the photo here. The DoniaLink accountant reviews
every receipt in **Expenses & Cash › POS Cash › Receipts**.

```
Employee ──photo──▶ Telegram group ──▶ DoniaLink Platform (bot) ──agent tools──▶ Odoo: Receipts (To Review)
                                                                                   │              │
                                                                               Payable         Cashier
                                                                            Create Bill    Match POS cash-out
```

## What it adds

| Area | Behaviour |
|---|---|
| Receipts | Reference `R-0153`, photos (an album = one receipt), sender, group, date, *Paid by* (Cashier / Payable / Not specified), note. Status To Review → Processed / Rejected / Duplicate. |
| Create Purchase Order | Main action for *Payable* photos: opens a new RFQ prefilled with the vendor, date and source (`R-0153`); the accountant adds the product lines and confirms. Saving it links it and copies the photos on the order; the vendor bill created from it gets them too. |
| Create Expense | For costs that are not stock purchases (repairs, rent…): a new expense prefilled from the receipt ("To Pay Later" bill by default). |
| Match Cash-Out | Suggests the cash-outs of the session open when the photo was sent (without receipt first, closest amount). Matching attaches the photos on the cash-out and, if it is not classified yet, classifies it with the receipt's category. **No second expense** is recorded. An amount difference is shown as a warning. One cash-out can have several receipts. |
| Ask Question | The bot posts the question in the group as a reply under the photo; the answer comes back in the receipt chatter (status *Waiting for Answer → Answered*). |
| Duplicates | Same Telegram file (`file_unique_id`, kept when forwarded) or same bytes as an earlier receipt → warning banner + one-click *Mark Duplicate*. Never closed automatically. |
| Telegram Senders | Created automatically on the first photo (Configuration › Telegram Senders). Rename to the employee name; switch *Accepted* off and the bot ignores that person. |
| Session Review | Counters *Cash-outs without receipt* and *Receipts not matched*, a Receipts tab, receipt count per cash-out. Per POS (Settings › Point of Sale › Accounting) **Cash-Outs Need a Receipt** blocks *Mark as Reviewed* until both are zero. |
| Overview | Tile "X receipts to review · oldest Y days". |

## Setup

1. Install **Purchase**, **Telegram Reports** (18.0.2.3.0+), **DoniaLink Agent Connector** and this module; connect the
   database to the DoniaLink Platform (Settings › DoniaLink Agent).
2. On the platform's **/telegram** page, link the client's staff group, pick its **company** and switch
   **Receipts** on.
3. **One-time bot setting (BotFather):** with privacy mode on, a bot in a group only sees commands and replies
   to itself, so photos never reach it. In @BotFather: `/setprivacy` → choose the bot → **Disable**, then
   **remove the bot from existing groups and add it again** (or make it a group admin).
4. Optional: tick *Cash-Outs Need a Receipt* on the POS that must prove every cash-out.

## Agent tools (called by the platform)

All are `write` tools of category `receipts` (the platform allows exactly these for the bot flow).

| Tool | When | Main result / errors |
|---|---|---|
| `receipt_create` | once per photo message | `receipt_id`, `reference`, `is_new_receipt`, `duplicate_of`, `summary_text` · idempotent on (chat_id, message_id) · `sender_ignored` |
| `receipt_update` | sender answered *who paid* / *note* | `summary_text` ("✅ Received R-0153 — Cashier · gas cylinder") · `not_the_sender`, `not_found` |
| `receipt_reply` | reply under an accountant question or under the photo | `receipt_id` · `not_found` (ignore), `sender_ignored` |

Odoo → platform: `POST /api/agents/telegram/reply` `{company_id, chat_id, reply_to_message_id, text}` →
`{ok, delivered, message_id}` (`telegram.service.send_reply`, Telegram Reports).

## Local testing without the platform (fake bot)

`scripts/fake_bot.py` calls the three tools over HTTP with an agent key, exactly like the platform will.
Run it **inside the Odoo container** (a native Odoo on the host may own `localhost:8069`):

```bash
B="docker exec -e ODOO_URL=http://localhost:8069 -e ODOO_DB=steve -e AGENT_KEY=<agent key> odoo18-web-1 \
   python3 /mnt/extra-addons/expense_cash_control_telegram/scripts/fake_bot.py"
$B photo /mnt/extra-addons/<some image> --paid cashier --note "gas cylinder"      # cashier receipt
$B --user 222 --name Omar photo img1.jpg img2.jpg --paid payable --note "flour"    # album, payable
$B photo <same image again>                                                         # duplicate warning
$B reply <message id printed above> "it was 25,000"                                 # reply -> chatter
```

Create the agent key in Odoo (Settings › DoniaLink Agent › agent keys) or with `odoo shell`.
*Ask Question* needs the platform's `/api/agents/telegram/reply`; until it exists it shows an error.

## Tests

```bash
odoo -d DB -u expense_cash_control_telegram --test-enable --test-tags /expense_cash_control_telegram --stop-after-init
```

## Owner cash box (phase 2)

Menu **Expenses & Cash › Owner Cash** (Cash Boxes, Movements, Differences, Statements).

| | |
|---|---|
| Cash box | One per owner **or partner**: its own cash journal ("Owner Cash – Ali"), an Owner Drawings (equity) account, optional deposit bank and till, and a POS category **"Owner collection – Ali"**. |
| Balance | Sum of the box movements, computed by Odoo: collected − expenses − took for me − deposits ± adjustments. **Negative = the business owes the owner.** The cash account balance is shown next to it for checking. |
| Collect | (1) At closing: POS **Cash Out** with the "Owner collection – Ali" category → collected automatically (what stays in the drawer is the float). (2) Later from the bot: *Yes, all* / *Other amount*, posted as a cash out of the POS cash journal. A session is collected once and never above its counted cash; *Other amount* opens a difference (left in till / loss / error). Session Review shows *Collected by Ali on …* / *Partially collected* / *Not collected*. |
| Expense | Photo + amount + category (categories flagged *Owner Expense Button*) → a **Paid Now** expense from his box, at once. It lands in **Receipts** tagged *Owner*: *Mark Reviewed*, fix the expense, *Reject / Duplicate* (the amount goes back to his box) or **Convert to Purchase Order** (the expense is removed; paying the PO's bill from his cash journal lowers the box again). |
| Took for me | Owner box → Owner Drawings (equity). Never an expense, so profit stays right. |
| Deposit | Bank: owner box → internal transfer account (match it with the bank statement). Till: cash in of the POS cash journal. |
| Count my cash | A count different from the balance opens a difference; *Loss / Gain* with a category posts the adjustment. |
| Statements | Weekly (chosen day) or monthly per box, sent by the bot with ✅ Correct / ⚠️ Not correct; a dispute opens a difference. *Send Statement Now* on the box. |
| Linking | *Telegram Link* on the box creates a one-time code registered on the platform; the owner opens `t.me/<bot>?start=<code>` once. Only the linked Telegram user can use the box. |

Agent tools (category `owner`): `owner_link`, `owner_boxes`, `owner_card`, `owner_sessions`, `owner_collect`,
`owner_categories`, `owner_expense`, `owner_took`, `owner_deposit`, `owner_moves`, `owner_count`,
`owner_statement_answer`. Odoo → platform: `POST /api/agents/telegram/owner-link` and
`POST /api/agents/telegram/owner` (`kind` = `session_closed` | `statement`).
The fake bot has `owner …` commands (see `scripts/fake_bot.py --help`).
