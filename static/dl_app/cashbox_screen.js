/** @odoo-module ignore **/
/* DoniaLink App: the owner cash box (was the Owner App at /ecc/owner/app).
 *
 * Addresses: #cashbox (home), #cashbox/collect | expense | took | deposit | count | moves | statements |
 * notifications, #cashbox/card/<id>[/withdraw|expense|count|deposit]. A notification may put the box first:
 * #cashbox/<box id>/statements. Every call goes to the old owner app's API (/dl/app/cashbox/api/<action>), and
 * every write carries a request id: tapping Save again after a lost connection never records it twice. */
(function () {
    'use strict';
    const app = window.DLApp;
    const { h, t } = app;
    const KEY = 'cashbox';

    app.text({
        ar: {
            'Cash box': 'صندوق المالك', 'Your cash, sessions to collect, expenses': 'نقدك، الجلسات للاستلام، المصاريف',
            'Your cash': 'رصيدك النقدي', 'The business owes you': 'الشركة مدينة لك بـ',
            'Sessions not collected': 'جلسات لم تُستلم', 'Collect': 'استلام', 'Expense': 'مصروف',
            'Took for me': 'سحب شخصي', 'Deposit': 'إيداع', 'Count cash': 'عدّ النقد', 'History': 'الحركات',
            'Statements': 'الكشوفات', 'Reminders': 'التذكيرات', 'Closed sessions to collect': 'جلسات مغلقة للاستلام',
            'All closed sessions are collected ✅': 'كل الجلسات المغلقة مستلمة ✅', 'Collect all': 'استلام الكل',
            'Other amount': 'مبلغ آخر', 'Collect this amount': 'استلام هذا المبلغ',
            'The rest goes to the accountant to explain (left in till, loss...).': 'الباقي يذهب للمحاسب ليوضحه (بقي في الصندوق، خسارة...).',
            'Amount': 'المبلغ', 'Category': 'الفئة', 'Note (optional)': 'ملاحظة (اختياري)', 'Receipt photos': 'صور الفاتورة',
            'Save': 'حفظ', 'Saving…': 'جارٍ الحفظ…', 'Add photo': 'إضافة صورة', 'Cancel': 'إلغاء',
            'Taken from your balance now; the accountant reviews it.': 'يُخصم من رصيدك فوراً، ويراجعه المحاسب.',
            'Cash for yourself (owner drawings), not a business expense.': 'سحب لنفسك (مسحوبات المالك)، ليس مصروفاً للشركة.',
            'Deposit to': 'إيداع إلى', 'Bank': 'البنك', 'POS till': 'صندوق الكاشير',
            'Type how much cash you hold now. Any difference goes to the accountant.': 'اكتب كم نقداً معك الآن. أي فرق يذهب للمحاسب.',
            'Counted cash': 'المبلغ المعدود', 'Check': 'تحقق', 'No movements yet.': 'لا توجد حركات بعد.',
            'No statements yet.': 'لا توجد كشوفات بعد.', 'Opening balance': 'الرصيد الافتتاحي', 'Collected': 'المستلم',
            'From cards': 'من البطاقات', 'Spent': 'المصاريف', 'Deposited': 'الإيداعات', 'Adjustments': 'التسويات',
            'Closing balance': 'الرصيد الختامي', '✅ Correct': '✅ صحيح', '⚠️ Not correct': '⚠️ غير صحيح',
            "What's wrong? (optional)": 'ما الخطأ؟ (اختياري)', 'New': 'جديد', 'Waiting for you': 'بانتظار ردك',
            'Confirmed': 'مؤكد', 'Disputed': 'مُعترض عليه', 'A statement waits for your answer': 'كشف بانتظار ردك',
            'Tap to review': 'اضغط للمراجعة', 'Nothing recorded today': 'لم تسجّل شيئاً اليوم',
            'Spent cash today? Record it now': 'صرفت نقداً اليوم؟ سجّله الآن',
            'Session closed': 'إغلاق جلسة', 'When a session closes with cash to collect': 'عند إغلاق جلسة فيها نقد للاستلام',
            'Daily expense reminder': 'تذكير يومي بالمصاريف', 'If you recorded no expense that day': 'إن لم تسجّل أي مصروف في ذلك اليوم',
            'Weekly cash count reminder': 'تذكير أسبوعي بعدّ النقد', 'Reminder hour': 'ساعة التذكير', 'Never': 'أبداً',
            'Saved': 'تم الحفظ', 'Sent to this app, Telegram and the DoniaLink platform': 'تصلك على هذا التطبيق وتيليجرام ومنصة دنيا لينك',
            'Notifications on this phone': 'الإشعارات على هذا الهاتف',
            'Monday': 'الاثنين', 'Tuesday': 'الثلاثاء', 'Wednesday': 'الأربعاء', 'Thursday': 'الخميس',
            'Friday': 'الجمعة', 'Saturday': 'السبت', 'Sunday': 'الأحد',
            'Done': 'تم', 'New balance': 'الرصيد الجديد', 'Back to the cash box': 'العودة للصندوق',
            'Collected {0} from {1}': 'تم استلام {0} من {1}',
            'Expense {0} ({1}) recorded · waiting for accountant review': 'تم تسجيل مصروف {0} ({1}) · بانتظار مراجعة المحاسب',
            'Took {0} for you': 'تم تسجيل سحب {0} لك', 'Deposited {0} to {1}': 'تم إيداع {0} إلى {1}',
            '{0} — it matches the books ✅': '{0} — مطابق للسجلات ✅',
            'You counted {0}, the books say {1} (difference {2}). The accountant will check it.': 'عددت {0} والسجلات تقول {1} (الفرق {2}). سيتحقق المحاسب.',
            'Thank you, statement confirmed.': 'شكراً، تم تأكيد الكشف.',
            'Noted. The accountant will check the statement with you.': 'تم التسجيل. سيراجع المحاسب الكشف معك.',
            'Already saved ✅': 'محفوظ مسبقاً ✅', 'Enter the amount.': 'اكتب المبلغ.', 'Choose a category.': 'اختر الفئة.',
            'Switch cash box': 'تغيير الصندوق', 'Collect {0} from {1}?': 'استلام {0} من {1}؟',
            'In review': 'قيد المراجعة', 'Closed': 'أُغلقت',
            'Bank entry': 'قيد بنكي', 'Adjustment': 'تسوية', 'From card': 'من البطاقة', 'Card sales': 'مبيعات البطاقة',
            'Cash withdrawal': 'سحب نقد', 'Cards': 'البطاقات', 'Card balance': 'رصيد البطاقة', 'Withdraw cash': 'سحب نقد',
            'Pay by card': 'دفع بالبطاقة', 'Check balance': 'مطابقة الرصيد', 'Card history': 'حركات البطاقة',
            'Deposit to card': 'إيداع في البطاقة', 'To my cash box': 'إلى صندوقي النقدي', 'The cash goes': 'النقد يذهب إلى',
            'To your cash box: it stays business cash you hold. Took for me: owner drawings.': 'إلى صندوقك: يبقى نقداً للشركة معك. سحب شخصي: مسحوبات المالك.',
            'Taken from the card balance now; the accountant reviews it.': 'يُخصم من رصيد البطاقة فوراً، ويراجعه المحاسب.',
            'Type the balance your bank app shows now. Any difference goes to the accountant.': 'اكتب الرصيد الظاهر في تطبيق البنك الآن. أي فرق يذهب للمحاسب.',
            'Bank balance': 'رصيد البنك',
            'The bank shows {0}, the books say {1} (difference {2}). The accountant will check it.': 'البنك يظهر {0} والسجلات تقول {1} (الفرق {2}). سيتحقق المحاسب.',
            '{0} from {1} added to your cash': 'تمت إضافة {0} من {1} إلى نقدك',
            'Took {0} for you from {1}': 'تم سحب {0} لك من {1}',
            'Card expense {0} ({1}) recorded · waiting for accountant review': 'تم تسجيل مصروف بالبطاقة {0} ({1}) · بانتظار مراجعة المحاسب',
            'by {0}': 'بواسطة {0}', 'Back to the card': 'العودة للبطاقة',
            'No cash box is linked to your login. Ask the accountant.': 'لا يوجد صندوق مرتبط بحسابك. اسأل المحاسب.',
            'This cash box is not yours.': 'هذا الصندوق ليس لك.',
            'The app works alongside the Telegram bot: what you record here shows there too.': 'يعمل التطبيق مع بوت تيليجرام: كل ما تسجله هنا يظهر هناك أيضاً.',
        },
    });

    const TYPES = {
        bank: 'Bank entry', collect: 'Collected', expense: 'Expense', drawing: 'Took for me', deposit: 'Deposit',
        adjust: 'Adjustment', from_card: 'From card', sales: 'Card sales', withdraw: 'Cash withdrawal',
    };
    const FIGURES = {
        opening: 'Opening balance', collected: 'Collected', from_card: 'From cards', spent: 'Spent', took: 'Took for me',
        deposited: 'Deposited', adjusted: 'Adjustments', closing: 'Closing balance',
    };
    const ST_STATES = { draft: 'New', sent: 'Waiting for you', confirmed: 'Confirmed', disputed: 'Disputed' };
    const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const MAX_PHOTOS = 5;

    // what the screen remembers between its pages (the page itself is redrawn on each address)
    const S = { boxes: null, boxId: null, card: null, sessions: [], pending: 0, categories: {}, bank: null };

    const store = {
        get(key) { try { return window.localStorage.getItem('dl-cashbox-' + key); } catch (e) { return null; } },
        set(key, value) { try { window.localStorage.setItem('dl-cashbox-' + key, value); } catch (e) { /* private mode */ } },
    };

    const call = (action, params) => app.call('/dl/app/cashbox/api/' + action, params);
    const go = (sub) => app.go('#' + KEY + (sub ? '/' + sub : ''));

    function newUid() {
        const bytes = new Uint8Array(16);
        window.crypto.getRandomValues(bytes);
        return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    }

    // ------------------------------------------------------------------ money
    const decimals = () => (S.card && Number.isInteger(S.card.decimals) ? S.card.decimals : 0);
    const symbol = () => (S.card && (S.card.currency_symbol || S.card.currency)) || '';
    const number = (value) => new Intl.NumberFormat('en-US', {
        minimumFractionDigits: decimals(), maximumFractionDigits: decimals(),
    }).format(Math.abs(Number(value) || 0));
    const money = (value) => `${Number(value) < 0 ? '−' : ''}${number(value)} ${symbol()}`.trim();
    const ltr = (text, cls) => h('bdi', { dir: 'ltr', class: cls || null }, text);

    const normalizeDigits = (text) => String(text || '')
        .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
        .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06F0));
    function parseAmount(text) {
        const clean = normalizeDigits(text).replace(/[\s,٬،]/g, '').replace(/٫/g, '.').replace(/[^0-9.]/g, '');
        if (!clean || clean === '.') {
            return null;
        }
        const value = parseFloat(clean);
        return Number.isFinite(value) ? value : null;
    }
    function formatTyping(input) {
        const raw = normalizeDigits(input.value).replace(/[^0-9.]/g, '');
        if (!raw) {
            input.value = '';
            return;
        }
        const [whole, ...rest] = raw.split('.');
        const grouped = (whole || '0').replace(/^0+(?=\d)/, '').replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        input.value = decimals() && rest.length ? `${grouped}.${rest.join('').slice(0, decimals())}` : grouped;
    }

    // ------------------------------------------------------------------ data
    async function loadBoxes(force) {
        if (S.boxes && !force) {
            return;
        }
        const info = await call('session');
        S.boxes = info.boxes || [];
        if (!S.boxes.find((b) => b.box_id === S.boxId)) {
            const saved = parseInt(store.get('box') || '0', 10);
            pickBox(saved);
        }
    }

    function pickBox(id) {
        const box = (S.boxes || []).find((b) => b.box_id === id) || (S.boxes || [])[0] || null;
        if (!box) {
            S.boxId = null;
            S.card = null;
            return false;
        }
        if (box.box_id !== S.boxId) {
            S.boxId = box.box_id;
            S.card = box;
            S.sessions = [];
            S.pending = 0;
            S.bank = null;
        }
        store.set('box', String(box.box_id));
        return box.box_id === id;
    }

    async function loadHome() {
        const data = await call('home', { box_id: S.boxId });
        S.card = data.card;
        S.sessions = data.sessions || [];
        S.pending = data.pending_statements || 0;
    }

    async function categories() {
        if (!S.categories[S.boxId]) {
            S.categories[S.boxId] = (await call('categories', { box_id: S.boxId })).categories || [];
        }
        return S.categories[S.boxId];
    }

    // ------------------------------------------------------------------ pieces
    function topbar(title, back) {
        const bar = app.topbar(title, true);
        if (back !== undefined) {
            // inside the cash box, "back" goes to its home (a notification may have opened a sub-page directly)
            const button = bar.querySelector('button');
            const fresh = button.cloneNode(true);
            fresh.addEventListener('click', () => (back === null ? app.go('') : go(back)));
            button.replaceWith(fresh);
        }
        return bar;
    }

    function spinner() {
        return h('div', { class: 'dl-splash dl-cb-wait' }, h('div', { class: 'dl-spinner' }));
    }

    function errorBox(container, message) {
        let box = container.querySelector(':scope > .dl-error');
        if (!box) {
            box = h('div', { class: 'dl-error', role: 'alert' });
            container.append(box);
        }
        box.textContent = message || t('Server error. Try again.');
    }

    function busy(button, on) {
        if (!button) {
            return;
        }
        button.disabled = on;
        if (on) {
            button.dataset.label = button.textContent;
            button.textContent = t('Saving…');
        } else if (button.dataset.label) {
            button.textContent = button.dataset.label;
        }
    }

    function action(sub, icon, label, badge) {
        return h('a', { class: 'dl-cb-action', href: '#' + KEY + '/' + sub }, [
            h('span', { class: 'dl-cb-action-ico', 'aria-hidden': 'true' }, icon),
            h('span', {}, label),
            badge ? h('span', { class: 'dl-count' }, String(badge)) : null,
        ]);
    }

    function amountField(label) {
        const input = h('input', { class: 'dl-input dl-cb-money', id: 'cb-amount', inputmode: 'decimal', autocomplete: 'off',
            placeholder: '0', dir: 'ltr', oninput: () => formatTyping(input) });
        setTimeout(() => input.focus(), 60);
        return [h('label', { class: 'dl-label', for: 'cb-amount' }, label || t('Amount')), input];
    }

    function noteField() {
        return [h('label', { class: 'dl-label', for: 'cb-note' }, t('Note (optional)')),
            h('textarea', { class: 'dl-input', id: 'cb-note', maxlength: '500', rows: '2' })];
    }

    function choices(options, selected, onPick) {
        // options: [{value, label, disabled}]
        const wrap = h('div', { class: 'dl-cb-chips', role: 'radiogroup' });
        for (const option of options) {
            wrap.append(h('button', {
                type: 'button', class: 'dl-cb-chip', role: 'radio', 'aria-checked': String(option.value === selected),
                disabled: option.disabled || false,
                onclick: (event) => {
                    wrap.querySelectorAll('button').forEach((b) => b.setAttribute('aria-checked', String(b === event.currentTarget)));
                    onPick(option.value);
                },
            }, option.label));
        }
        return wrap;
    }

    function moveRow(m) {
        return h('div', { class: 'dl-cb-row' }, [
            h('span', { class: 'dl-cb-row-main' }, [
                h('span', { class: 'dl-cb-row-title' }, [t(TYPES[m.type] || m.type_label || m.type),
                    m.review === 'to_review' ? h('span', { class: 'dl-cb-pill warn' }, t('In review')) : null]),
                h('span', { class: 'dl-cb-row-desc' }, m.description || ''),
                h('span', { class: 'dl-cb-row-small' }, [ltr(m.local_date || ''),
                    m.owner ? ' · ' + t('by {0}', m.owner) : '']),
            ]),
            h('span', { class: 'dl-cb-row-side' }, [
                ltr(`${m.amount >= 0 ? '+' : ''}${money(m.amount)}`, 'dl-cb-num ' + (m.amount >= 0 ? 'in' : 'out')),
                h('span', { class: 'dl-cb-row-small' }, ['→ ', ltr(money(m.balance_after))]),
            ]),
        ]);
    }

    function sessionRow(s) {
        return h('button', { type: 'button', class: 'dl-cb-row dl-cb-tap', onclick: () => collectSheet(s) }, [
            h('span', { class: 'dl-cb-row-main' }, [
                h('span', { class: 'dl-cb-row-title' }, [s.name,
                    s.state === 'partial' ? h('span', { class: 'dl-cb-pill warn' }, '½') : null]),
                h('span', { class: 'dl-cb-row-desc' }, [s.pos, ' · ', t('Closed'), ' ', ltr(s.closed_at || '')]),
            ]),
            ltr(money(s.amount), 'dl-cb-num in'),
        ]);
    }

    function cardRow(c) {
        return h('a', { class: 'dl-cb-row dl-cb-tap', href: `#${KEY}/card/${c.card_id}` }, [
            h('span', { class: 'dl-cb-row-main' }, [
                h('span', { class: 'dl-cb-row-title' }, ['💳 ', c.name]),
                h('span', { class: 'dl-cb-row-desc' }, c.bank || ''),
            ]),
            ltr(money(c.balance), 'dl-cb-num ' + (c.balance < 0 ? 'out' : 'in')),
        ]);
    }

    // a sheet from the bottom of the screen
    function sheet(children) {
        const close = () => backdrop.remove();
        const panel = h('section', { class: 'dl-cb-sheet', role: 'dialog', 'aria-modal': 'true' }, children(close));
        const backdrop = h('div', { class: 'dl-cb-backdrop', onclick: (event) => { if (event.target === backdrop) { close(); } } }, panel);
        document.body.append(backdrop);
        window.addEventListener('hashchange', close, { once: true });
        return { panel, close };
    }

    // ------------------------------------------------------------------ the end of every write
    function done(el, result, text, opts) {
        if (result.card) {
            S.card = result.card;
        }
        if (result.sessions) {
            S.sessions = result.sessions;
        }
        if (result.bank_card) {
            S.bank = result.bank_card;
        }
        const options = opts || {};
        el.replaceChildren(
            topbar(t('Done'), ''),
            h('section', { class: 'dl-card dl-cb-done' }, [
                h('div', { class: 'dl-cb-done-ico', 'aria-hidden': 'true' }, '✅'),
                h('p', { class: 'dl-cb-done-text' }, text),
                result.bank_card ? h('p', { class: 'dl-muted' }, [t('Card balance'), ' · ', result.bank_card.name, ': ',
                    h('b', {}, ltr(money(result.bank_card.balance)))]) : null,
                h('p', { class: 'dl-muted' }, [t('New balance'), ': ', h('b', {}, ltr(money(S.card ? S.card.balance : 0)))]),
                options.card ? h('a', { class: 'dl-btn', href: `#${KEY}/card/${options.card}` }, t('Back to the card')) : null,
                h('a', { class: 'dl-btn' + (options.card ? ' ghost' : ''), href: '#' + KEY }, t('Back to the cash box')),
            ]),
        );
        app.toast(text, 'ok');
        if (navigator.vibrate) {
            navigator.vibrate(30);
        }
        window.scrollTo(0, 0);
        app.refreshBadges();
    }

    // a form whose Save keeps the same request id until it succeeds
    function form(el, children, submit, label) {
        const button = h('button', { type: 'submit', class: 'dl-btn' }, label || t('Save'));
        const node = h('form', { class: 'dl-card dl-cb-form', novalidate: true }, [...children, button]);
        node.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (button.disabled) {
                return;
            }
            busy(button, true);
            try {
                const out = await submit();
                busy(button, false);
                done(el, out[0], out[1], out[2]);
            } catch (e) {
                busy(button, false);
                errorBox(node, e.message);
            }
        });
        return node;
    }

    // ------------------------------------------------------------------ home
    async function renderHome(el) {
        el.append(topbar(t('Cash box'), null), spinner());
        await loadHome();
        const c = S.card;
        const switcher = S.boxes.length > 1 ? h('label', { class: 'dl-cb-switch' }, [
            h('span', { class: 'dl-muted' }, t('Switch cash box')),
            h('select', { class: 'dl-input', onchange: (event) => { pickBox(parseInt(event.target.value, 10)); go(''); app.route(); } },
                S.boxes.map((b) => h('option', { value: b.box_id, selected: b.box_id === S.boxId }, `${b.owner} · ${b.company}`))),
        ]) : null;
        const moreSessions = S.sessions.length > 3
            ? h('a', { class: 'dl-cb-row dl-cb-tap', href: `#${KEY}/collect` }, h('b', {}, `+${S.sessions.length - 3}`)) : null;
        el.replaceChildren(
            topbar(c.owner || t('Cash box'), null),
            switcher,
            h('section', { class: 'dl-cb-balance' }, [
                h('div', { class: 'dl-cb-balance-label' }, [t('Your cash'), c.company ? h('span', {}, ' · ' + c.company) : null]),
                h('div', { class: 'dl-cb-balance-amount' }, ltr(money(c.balance))),
                c.balance < 0 ? h('div', { class: 'dl-cb-owes' }, [t('The business owes you'), ' ', h('b', {}, ltr(money(-c.balance)))]) : null,
                h('div', { class: 'dl-cb-balance-meta' }, [
                    h('span', {}, [t('Sessions not collected'), ': ', h('b', {}, String(c.uncollected_sessions || 0))]),
                    c.uncollected_sessions ? ltr(money(c.uncollected_amount)) : null,
                ]),
            ]),
            c.expense_reminder_due ? h('a', { class: 'dl-cb-banner', href: `#${KEY}/expense` }, [
                h('span', { 'aria-hidden': 'true' }, '🧾'),
                h('span', {}, [h('b', {}, t('Nothing recorded today')), h('span', {}, t('Spent cash today? Record it now'))]),
            ]) : null,
            S.pending ? h('a', { class: 'dl-cb-banner warn', href: `#${KEY}/statements` }, [
                h('span', { 'aria-hidden': 'true' }, '📄'),
                h('span', {}, [h('b', {}, t('A statement waits for your answer')), h('span', {}, t('Tap to review'))]),
            ]) : null,
            h('nav', { class: 'dl-cb-grid' }, [
                action('collect', '💰', t('Collect'), c.uncollected_sessions),
                action('expense', '🧾', t('Expense')),
                action('took', '👛', t('Took for me')),
                action('deposit', '🏦', t('Deposit')),
                action('count', '🔢', t('Count cash')),
                action('moves', '📜', t('History')),
                action('statements', '📄', t('Statements'), S.pending),
                action('notifications', '🔔', t('Reminders')),
            ]),
            (c.cards || []).length ? h('section', { class: 'dl-card flush' }, [
                h('h2', { class: 'dl-cb-head' }, t('Cards')), ...c.cards.map(cardRow)]) : null,
            h('section', { class: 'dl-card flush' }, [
                h('h2', { class: 'dl-cb-head' }, t('Closed sessions to collect')),
                ...(S.sessions.length ? S.sessions.slice(0, 3).map(sessionRow)
                    : [h('p', { class: 'dl-empty' }, t('All closed sessions are collected ✅'))]),
                moreSessions,
            ]),
            h('p', { class: 'dl-footer' }, t('The app works alongside the Telegram bot: what you record here shows there too.')),
        );
    }

    // ------------------------------------------------------------------ collect
    async function renderCollect(el) {
        el.append(topbar(t('Collect'), ''), spinner());
        await loadHome();
        el.replaceChildren(topbar(t('Collect'), ''), h('section', { class: 'dl-card flush' },
            S.sessions.length ? S.sessions.map(sessionRow) : h('p', { class: 'dl-empty' }, t('All closed sessions are collected ✅'))));
    }

    function collectSheet(session) {
        const uid = newUid();
        const input = h('input', { class: 'dl-input dl-cb-money', id: 'cb-other', inputmode: 'decimal', autocomplete: 'off',
            placeholder: '0', dir: 'ltr', oninput: () => formatTyping(input) });
        const { panel, close } = sheet((closeIt) => [
            h('h2', {}, session.name),
            h('p', { class: 'dl-muted' }, [session.pos, ' · ', ltr(session.closed_at || '')]),
            h('button', { type: 'button', class: 'dl-btn', 'data-all': '' }, [t('Collect all'), ' · ', ltr(money(session.amount))]),
            h('label', { class: 'dl-label', for: 'cb-other' }, t('Other amount')),
            input,
            h('p', { class: 'dl-muted dl-cb-hint' }, t('The rest goes to the accountant to explain (left in till, loss...).')),
            h('button', { type: 'button', class: 'dl-btn ghost', 'data-other': '' }, t('Collect this amount')),
            h('button', { type: 'button', class: 'dl-link', onclick: closeIt }, t('Cancel')),
        ]);
        const run = async (button, amount) => {
            busy(button, true);
            try {
                const result = await call('collect', { box_id: S.boxId, session_id: session.session_id, amount, request_uid: uid });
                close();
                const text = result.replayed ? t('Already saved ✅')
                    : t('Collected {0} from {1}', money(amount === null ? session.amount : amount), session.name);
                done(app.el.querySelector('.dl-screen'), result, text);
            } catch (e) {
                errorBox(panel, e.message);
            } finally {
                busy(button, false);
            }
        };
        panel.querySelector('[data-all]').addEventListener('click', (event) => run(event.currentTarget, null));
        panel.querySelector('[data-other]').addEventListener('click', (event) => {
            const amount = parseAmount(input.value);
            if (!amount) {
                errorBox(panel, t('Enter the amount.'));
                return;
            }
            run(event.currentTarget, amount);
        });
    }

    // ------------------------------------------------------------------ expense (cash or card)
    async function renderExpense(el, card) {
        el.append(topbar(card ? t('Pay by card') : t('Expense'), card ? `card/${card.card_id}` : ''));
        const uid = newUid();
        let category = null;
        const photos = [];
        const thumbs = h('div', { class: 'dl-cb-photos' });
        const file = h('input', { type: 'file', accept: 'image/*', capture: 'environment', hidden: true });
        const drawPhotos = () => {
            thumbs.replaceChildren(...photos.map((p, i) => h('div', { class: 'dl-cb-photo' }, [
                h('img', { src: 'data:image/jpeg;base64,' + p.b64, alt: '' }),
                h('button', { type: 'button', 'aria-label': '×', onclick: () => { photos.splice(i, 1); drawPhotos(); } }, '×'),
            ])), photos.length < MAX_PHOTOS ? h('button', { type: 'button', class: 'dl-cb-photo-add', 'aria-label': t('Add photo'),
                onclick: () => file.click() }, [app.icon('camera'), t('Add photo')]) : '');
        };
        file.addEventListener('change', async () => {
            const picked = Array.from(file.files || []);
            file.value = '';
            for (const item of picked) {
                if (photos.length >= MAX_PHOTOS) {
                    break;
                }
                try {
                    photos.push(await compress(item));
                } catch (e) {
                    app.toast(e.message, 'bad');
                }
            }
            drawPhotos();
        });
        drawPhotos();
        const cats = h('div', { class: 'dl-cb-chips' }, h('div', { class: 'dl-spinner' }));
        el.append(form(el, [
            ...amountField(),
            h('span', { class: 'dl-label' }, t('Category')), cats,
            h('span', { class: 'dl-label' }, t('Receipt photos')), thumbs, file,
            ...noteField(),
            h('p', { class: 'dl-muted dl-cb-hint' }, card ? t('Taken from the card balance now; the accountant reviews it.')
                : t('Taken from your balance now; the accountant reviews it.')),
        ], async () => {
            const amount = parseAmount(el.querySelector('#cb-amount').value);
            if (!amount) {
                throw new Error(t('Enter the amount.'));
            }
            if (!category) {
                throw new Error(t('Choose a category.'));
            }
            const list = await categories();
            const picked = list.find((x) => x.id === category);
            const result = await call(card ? 'card_expense' : 'expense', {
                box_id: S.boxId, card_id: card ? card.card_id : undefined, amount, category_id: category,
                note: el.querySelector('#cb-note').value, request_uid: uid,
                photos: photos.map((p) => ({ content_b64: p.b64, mimetype: 'image/jpeg', filename: p.name })),
            });
            const label = picked ? picked.name : '';
            return [result, result.replayed ? t('Already saved ✅')
                : t(card ? 'Card expense {0} ({1}) recorded · waiting for accountant review'
                    : 'Expense {0} ({1}) recorded · waiting for accountant review', money(amount), label),
            card ? { card: card.card_id } : {}];
        }));
        const list = await categories();
        cats.replaceWith(choices(list.map((x) => ({ value: x.id, label: x.name })), null, (value) => { category = value; }));
    }

    function compress(file) {
        // phones take 4-12 MB photos: send a 1600 px JPEG instead (fast on a weak connection)
        return new Promise((resolve, reject) => {
            const url = URL.createObjectURL(file);
            const img = new Image();
            img.onload = () => {
                const scale = Math.min(1, 1600 / Math.max(img.naturalWidth, img.naturalHeight));
                const canvas = document.createElement('canvas');
                canvas.width = Math.round(img.naturalWidth * scale);
                canvas.height = Math.round(img.naturalHeight * scale);
                canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
                URL.revokeObjectURL(url);
                const data = canvas.toDataURL('image/jpeg', 0.78);
                resolve({ b64: data.split(',')[1], name: (file.name || 'receipt').replace(/\.[^.]+$/, '') + '.jpg' });
            };
            img.onerror = () => { URL.revokeObjectURL(url); reject(new Error(t('Add photo'))); };
            img.src = url;
        });
    }

    // ------------------------------------------------------------------ took, deposit, count
    function renderTook(el) {
        const uid = newUid();
        el.append(topbar(t('Took for me'), ''), form(el, [
            ...amountField(), ...noteField(),
            h('p', { class: 'dl-muted dl-cb-hint' }, t('Cash for yourself (owner drawings), not a business expense.')),
        ], async () => {
            const amount = parseAmount(el.querySelector('#cb-amount').value);
            if (!amount) {
                throw new Error(t('Enter the amount.'));
            }
            const result = await call('took', { box_id: S.boxId, amount, note: el.querySelector('#cb-note').value, request_uid: uid });
            return [result, result.replayed ? t('Already saved ✅') : t('Took {0} for you', money(amount))];
        }));
    }

    function renderDeposit(el, card) {
        const c = S.card || {};
        const uid = newUid();
        let target = card ? `card:${card.card_id}` : 'bank';
        const options = [
            { value: 'bank', label: '🏦 ' + (c.bank_name || t('Bank')) },
            { value: 'till', label: '🧮 ' + (c.till_name || t('POS till')), disabled: !c.till_available },
            ...(c.cards || []).map((x) => ({ value: `card:${x.card_id}`, label: '💳 ' + x.name })),
        ];
        el.append(topbar(card ? t('Deposit to card') : t('Deposit'), card ? `card/${card.card_id}` : ''), form(el, [
            ...amountField(),
            h('span', { class: 'dl-label' }, t('Deposit to')),
            choices(options, target, (value) => { target = value; }),
            ...noteField(),
        ], async () => {
            const amount = parseAmount(el.querySelector('#cb-amount').value);
            if (!amount) {
                throw new Error(t('Enter the amount.'));
            }
            let kind = target;
            let cardId;
            let name = target === 'bank' ? (c.bank_name || t('Bank')) : (c.till_name || t('POS till'));
            if (target.startsWith('card:')) {
                cardId = parseInt(target.slice(5), 10);
                const picked = (c.cards || []).find((x) => x.card_id === cardId);
                name = picked ? picked.name : '';
                kind = 'card';
            }
            const result = await call('deposit', { box_id: S.boxId, amount, target: kind, card_id: cardId,
                note: el.querySelector('#cb-note').value, request_uid: uid });
            return [result, result.replayed ? t('Already saved ✅') : t('Deposited {0} to {1}', money(amount), name),
                cardId ? { card: cardId } : {}];
        }));
    }

    function renderCount(el, card) {
        el.append(topbar(card ? t('Check balance') : t('Count cash'), card ? `card/${card.card_id}` : ''), form(el, [
            ...amountField(card ? t('Bank balance') : t('Counted cash')),
            h('p', { class: 'dl-muted dl-cb-hint' }, card
                ? t('Type the balance your bank app shows now. Any difference goes to the accountant.')
                : t('Type how much cash you hold now. Any difference goes to the accountant.')),
        ], async () => {
            const counted = parseAmount(el.querySelector('#cb-amount').value);
            if (counted === null) {
                throw new Error(t('Enter the amount.'));
            }
            const result = card ? await call('card_count', { box_id: S.boxId, card_id: card.card_id, counted })
                : await call('count', { box_id: S.boxId, counted });
            const text = result.difference
                ? t(card ? 'The bank shows {0}, the books say {1} (difference {2}). The accountant will check it.'
                    : 'You counted {0}, the books say {1} (difference {2}). The accountant will check it.',
                money(counted), money(result.expected), money(result.difference))
                : t('{0} — it matches the books ✅', money(counted));
            return [result, text, card ? { card: card.card_id } : {}];
        }, t('Check')));
    }

    // ------------------------------------------------------------------ history, statements
    async function renderMoves(el) {
        el.append(topbar(t('History'), ''), spinner());
        const data = await call('moves', { box_id: S.boxId, limit: 50 });
        S.card = data.card || S.card;
        el.replaceChildren(topbar(t('History'), ''), h('section', { class: 'dl-card flush' },
            (data.moves || []).length ? data.moves.map(moveRow) : h('p', { class: 'dl-empty' }, t('No movements yet.'))));
    }

    async function renderStatements(el) {
        el.append(topbar(t('Statements'), ''), spinner());
        const data = await call('statements', { box_id: S.boxId });
        const list = h('div', { class: 'dl-stack' });
        el.replaceChildren(topbar(t('Statements'), ''), list);
        drawStatements(list, data.statements || []);
    }

    function drawStatements(list, statements) {
        S.pending = statements.filter((s) => s.state === 'sent').length;
        list.replaceChildren(...(statements.length ? statements.map((s) => {
            const figures = s.figures.filter(([key, value]) => (key !== 'adjusted' && key !== 'from_card') || value).map(([key, value]) => {
                const sign = { collected: '+', from_card: '+', spent: '−', took: '−', deposited: '−' }[key] || '';
                const cls = key === 'closing' ? 'total' : '';
                return [h('span', { class: cls }, t(FIGURES[key] || key)),
                    h('span', { class: 'dl-cb-fig ' + cls }, ltr(sign ? `${sign}${number(value)} ${symbol()}` : money(value)))];
            }).flat();
            const card = h('section', { class: 'dl-card' }, [
                h('div', { class: 'dl-card-head' }, [h('b', {}, ltr(`${s.date_from} → ${s.date_to}`)),
                    h('span', { class: 'dl-cb-pill' + (s.can_answer ? ' warn' : '') }, t(ST_STATES[s.state] || s.state))]),
                h('div', { class: 'dl-cb-figs' }, figures),
                s.closing < 0 ? h('p', { class: 'dl-muted' }, [t('The business owes you'), ' ', h('b', {}, ltr(money(-s.closing)))]) : null,
            ]);
            if (s.can_answer) {
                const note = h('textarea', { class: 'dl-input', id: `cb-st-${s.id}`, maxlength: '500', rows: '2' });
                const answer = async (button, correct) => {
                    busy(button, true);
                    try {
                        const result = await call('statement_answer', { box_id: S.boxId, statement_id: s.id, correct, note: note.value });
                        app.toast(correct ? t('Thank you, statement confirmed.') : t('Noted. The accountant will check the statement with you.'), 'ok');
                        drawStatements(list, result.statements || []);
                        app.refreshBadges();
                    } catch (e) {
                        busy(button, false);
                        errorBox(card, e.message);
                    }
                };
                card.append(h('label', { class: 'dl-label', for: `cb-st-${s.id}` }, t("What's wrong? (optional)")), note,
                    h('div', { class: 'dl-cb-two' }, [
                        h('button', { type: 'button', class: 'dl-btn', onclick: (e) => answer(e.currentTarget, true) }, t('✅ Correct')),
                        h('button', { type: 'button', class: 'dl-btn dl-cb-danger', onclick: (e) => answer(e.currentTarget, false) }, t('⚠️ Not correct')),
                    ]));
            } else if (s.answer_note) {
                card.append(h('p', { class: 'dl-muted' }, s.answer_note));
            }
            return card;
        }) : [h('section', { class: 'dl-card' }, h('p', { class: 'dl-empty' }, t('No statements yet.')))]));
    }

    // ------------------------------------------------------------------ cards
    async function loadCard(cardId) {
        const data = await call('card_home', { box_id: S.boxId, card_id: cardId, limit: 50 });
        S.bank = data.bank_card;
        S.card = data.card || S.card;
        return data;
    }

    async function renderCard(el, cardId) {
        el.append(topbar(t('Cards'), ''), spinner());
        const data = await loadCard(cardId);
        const bank = data.bank_card;
        el.replaceChildren(
            topbar(bank.name, ''),
            h('section', { class: 'dl-cb-balance' }, [
                h('div', { class: 'dl-cb-balance-label' }, ['💳 ', t('Card balance'), bank.bank ? h('span', {}, ' · ' + bank.bank) : null]),
                h('div', { class: 'dl-cb-balance-amount' }, ltr(money(bank.balance))),
            ]),
            h('nav', { class: 'dl-cb-grid' }, [
                action(`card/${cardId}/withdraw`, '💵', t('Withdraw cash')),
                action(`card/${cardId}/expense`, '🧾', t('Pay by card')),
                action(`card/${cardId}/count`, '🔢', t('Check balance')),
                action(`card/${cardId}/deposit`, '🏦', t('Deposit to card')),
            ]),
            h('section', { class: 'dl-card flush' }, [h('h2', { class: 'dl-cb-head' }, t('Card history')),
                ...((data.moves || []).length ? data.moves.map(moveRow) : [h('p', { class: 'dl-empty' }, t('No movements yet.'))])]),
        );
    }

    function renderWithdraw(el, card) {
        const uid = newUid();
        let target = 'box';
        el.append(topbar(t('Withdraw cash'), `card/${card.card_id}`), form(el, [
            ...amountField(),
            h('span', { class: 'dl-label' }, t('The cash goes')),
            choices([{ value: 'box', label: '👛 ' + t('To my cash box') }, { value: 'took', label: '🙋 ' + t('Took for me') }],
                target, (value) => { target = value; }),
            h('p', { class: 'dl-muted dl-cb-hint' }, t('To your cash box: it stays business cash you hold. Took for me: owner drawings.')),
            ...noteField(),
        ], async () => {
            const amount = parseAmount(el.querySelector('#cb-amount').value);
            if (!amount) {
                throw new Error(t('Enter the amount.'));
            }
            const result = await call('card_withdraw', { box_id: S.boxId, card_id: card.card_id, amount, target,
                note: el.querySelector('#cb-note').value, request_uid: uid });
            return [result, result.replayed ? t('Already saved ✅')
                : t(target === 'took' ? 'Took {0} for you from {1}' : '{0} from {1} added to your cash', money(amount), card.name),
            { card: card.card_id }];
        }));
    }

    // ------------------------------------------------------------------ reminders
    async function renderNotifications(el) {
        el.append(topbar(t('Reminders'), ''), spinner());
        const n = (await call('notifications', { box_id: S.boxId })).notifications;
        const toggle = (id, on, title, desc) => h('label', { class: 'dl-switch', for: id }, [
            h('span', { class: 'dl-switch-text' }, [h('b', {}, title), h('span', {}, desc)]),
            h('input', { type: 'checkbox', id, checked: !!on }),
        ]);
        const days = h('select', { class: 'dl-input', id: 'cb-n-count' }, [
            h('option', { value: '', selected: !n.reminder_count_weekday }, t('Never')),
            ...WEEKDAYS.map((d, i) => h('option', { value: String(i), selected: n.reminder_count_weekday === String(i) }, t(d))),
        ]);
        const hours = h('select', { class: 'dl-input', id: 'cb-n-hour', dir: 'ltr' },
            Array.from({ length: 24 }, (_, hour) => h('option', { value: String(hour), selected: n.reminder_hour === hour },
                `${String(hour).padStart(2, '0')}:00`)));
        // saving the reminders goes back to the cash box (no "done" page)
        const node = h('form', { class: 'dl-card dl-cb-form', novalidate: true }, [
            h('div', { class: 'dl-switches' }, [
                toggle('cb-n-session', n.session_closed, t('Session closed'), t('When a session closes with cash to collect')),
                toggle('cb-n-expense', n.reminder_expense, t('Daily expense reminder'), t('If you recorded no expense that day')),
            ]),
            h('label', { class: 'dl-label', for: 'cb-n-count' }, t('Weekly cash count reminder')), days,
            h('label', { class: 'dl-label', for: 'cb-n-hour' }, t('Reminder hour')), hours,
            h('p', { class: 'dl-muted dl-cb-hint' }, t('Sent to this app, Telegram and the DoniaLink platform')),
            h('a', { href: '#settings' }, '🔔 ' + t('Notifications on this phone')),
            h('button', { type: 'submit', class: 'dl-btn' }, t('Save')),
        ]);
        node.addEventListener('submit', async (event) => {
            event.preventDefault();
            const button = node.querySelector('button[type=submit]');
            if (button.disabled) {
                return;
            }
            busy(button, true);
            try {
                await call('notifications_set', {
                    box_id: S.boxId,
                    session_closed: el.querySelector('#cb-n-session').checked,
                    reminder_expense: el.querySelector('#cb-n-expense').checked,
                    reminder_count_weekday: days.value || null,
                    reminder_hour: parseInt(hours.value, 10),
                });
                app.toast(t('Saved'), 'ok');
                go('');
            } catch (e) {
                busy(button, false);
                errorBox(node, e.message);
            }
        });
        el.replaceChildren(topbar(t('Reminders'), ''), node);
    }

    // ------------------------------------------------------------------ the screen
    app.screen(KEY, {
        title: () => t('Cash box'),
        async render(el, params) {
            const parts = (params || []).slice();
            await loadBoxes(!S.boxes || !parts.length);
            if (parts.length && /^\d+$/.test(parts[0])) {
                // opened from a notification: that box
                if (!pickBox(parseInt(parts.shift(), 10))) {
                    app.toast(t('This cash box is not yours.'), 'bad');
                }
            }
            if (!S.boxId) {
                el.append(topbar(t('Cash box'), null),
                    h('section', { class: 'dl-card' }, h('p', { class: 'dl-empty' }, t('No cash box is linked to your login. Ask the accountant.'))));
                return;
            }
            const [page, id, sub] = parts;
            try {
                if (page === 'card' && /^\d+$/.test(id || '')) {
                    const cardId = parseInt(id, 10);
                    if (!sub) {
                        return await renderCard(el, cardId);
                    }
                    const card = S.bank && S.bank.card_id === cardId ? S.bank : (await loadCard(cardId)).bank_card;
                    const pages = { withdraw: renderWithdraw, expense: renderExpense, count: renderCount, deposit: renderDeposit };
                    return pages[sub] ? pages[sub](el, card) : go(`card/${cardId}`);
                }
                const pages = {
                    collect: renderCollect, expense: renderExpense, took: renderTook, deposit: renderDeposit, count: renderCount,
                    moves: renderMoves, statements: renderStatements, notifications: renderNotifications,
                };
                return await (pages[page] || renderHome)(el);
            } catch (e) {
                el.replaceChildren(topbar(t('Cash box'), page ? '' : null), h('div', { class: 'dl-error' }, [
                    e.message || t('Server error. Try again.'),
                    h('button', { class: 'dl-btn', onclick: () => app.route() }, t('Try again')),
                ]));
                if (e.code === 'forbidden' || e.code === 'not_found') {
                    S.boxes = null;
                }
            }
        },
    });
})();
