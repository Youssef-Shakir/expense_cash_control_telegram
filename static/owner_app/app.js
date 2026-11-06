/* Owner App: the owner cash box of expense_cash_control_telegram as an installable web app.
   Same actions as the Telegram bot: collect POS sessions, expense with photos, took for me, deposit,
   count my cash, history, statements. Every write carries a request id: tapping Save again after a
   lost connection never records it twice. */
(function () {
    'use strict';

    // ------------------------------------------------------------------ texts
    const I18N = {
        ar: {
            appName: 'صندوق المالك', login: 'تسجيل الدخول', loginHint: 'ادخل باسم المستخدم الذي أعطاك إياه المحاسب.',
            user: 'اسم المستخدم', password: 'كلمة المرور', enter: 'دخول', balance: 'رصيدك النقدي',
            owes: 'الشركة مدينة لك بـ', toCollect: 'جلسات لم تُستلم', none: 'لا شيء',
            collect: 'استلام', expense: 'مصروف', took: 'سحب شخصي', deposit: 'إيداع', count: 'عدّ النقد',
            moves: 'الحركات', statements: 'الكشوفات', menu: 'القائمة', back: 'رجوع', refresh: 'تحديث',
            sessionsTitle: 'جلسات مغلقة للاستلام', noSessions: 'كل الجلسات المغلقة مستلمة ✅',
            collectAll: 'استلام الكل', otherAmount: 'مبلغ آخر', collectOther: 'استلام هذا المبلغ',
            otherHint: 'الباقي يذهب للمحاسب ليوضحه (بقي في الصندوق، خسارة...).',
            amount: 'المبلغ', category: 'الفئة', note: 'ملاحظة (اختياري)', photos: 'صور الفاتورة',
            save: 'حفظ', saving: 'جارٍ الحفظ…', addPhoto: 'إضافة صورة',
            expenseHint: 'يُخصم من رصيدك فوراً، ويراجعه المحاسب.',
            tookHint: 'سحب لنفسك (مسحوبات المالك)، ليس مصروفاً للشركة.',
            depositTo: 'إيداع إلى', bank: 'البنك', till: 'صندوق الكاشير',
            countHint: 'اكتب كم نقداً معك الآن. أي فرق يذهب للمحاسب.', counted: 'المبلغ المعدود',
            check: 'تحقق', noMoves: 'لا توجد حركات بعد.', noStatements: 'لا توجد كشوفات بعد.',
            stOpening: 'الرصيد الافتتاحي', stCollected: 'المستلم', stSpent: 'المصاريف', stTook: 'سحب شخصي',
            stDeposited: 'الإيداعات', stAdjusted: 'التسويات', stClosing: 'الرصيد الختامي',
            correct: '✅ صحيح', notCorrect: '⚠️ غير صحيح', whatsWrong: 'ما الخطأ؟ (اختياري)',
            stDraft: 'جديد', stSent: 'بانتظار ردك', stConfirmed: 'مؤكد', stDisputed: 'مُعترض عليه',
            pendingStatement: 'كشف بانتظار ردك', openIt: 'اضغط للمراجعة',
            done: 'تم', home: 'الرئيسية', newBalance: 'الرصيد الجديد',
            collected: (a, s) => `تم استلام ${a} من ${s}`,
            expenseDone: (a, c) => `تم تسجيل مصروف ${a} (${c}) · بانتظار مراجعة المحاسب`,
            tookDone: (a) => `تم تسجيل سحب ${a} لك`,
            depositDone: (a, t) => `تم إيداع ${a} إلى ${t}`,
            countOk: (a) => `${a} — مطابق للسجلات ✅`,
            countDiff: (a, e, d) => `عددت ${a} والسجلات تقول ${e} (الفرق ${d}). سيتحقق المحاسب.`,
            stThanks: 'شكراً، تم تأكيد الكشف.', stNoted: 'تم التسجيل. سيراجع المحاسب الكشف معك.',
            alreadySaved: 'محفوظ مسبقاً ✅',
            offline: 'لا يوجد اتصال بالإنترنت — لن يُحفظ شيء حتى يعود الاتصال.',
            network: 'انقطع الاتصال. لسنا متأكدين أنه حُفظ: اضغط حفظ مرة أخرى، لن يُسجَّل مرتين.',
            serverError: 'حدث خطأ في الخادم. حاول مرة أخرى.',
            needAmount: 'اكتب المبلغ.', needCategory: 'اختر الفئة.',
            language: 'English', install: 'تثبيت التطبيق', iosInstall: 'في سفاري: زر المشاركة ثم "إضافة إلى الشاشة الرئيسية".',
            switchBox: 'تغيير الصندوق', logout: 'تسجيل الخروج', confirmCollect: (a, s) => `استلام ${a} من ${s}؟`,
            confirm: 'تأكيد', cancel: 'إلغاء', waitingReview: 'قيد المراجعة', closedAt: 'أُغلقت',
            types: { collect: 'استلام', expense: 'مصروف', drawing: 'سحب شخصي', deposit: 'إيداع', adjust: 'تسوية' },
            telegramToo: 'يعمل التطبيق مع بوت تيليجرام: كل ما تسجله هنا يظهر هناك أيضاً.',
            poweredBy: 'بواسطة', developedBy: 'تطوير', developer: 'يوسف شاكر',
        },
        en: {
            appName: 'Owner Cash Box', login: 'Log in', loginHint: 'Use the login the accountant gave you.',
            user: 'Login', password: 'Password', enter: 'Log in', balance: 'Your cash',
            owes: 'The business owes you', toCollect: 'Sessions not collected', none: 'None',
            collect: 'Collect', expense: 'Expense', took: 'Took for me', deposit: 'Deposit', count: 'Count cash',
            moves: 'History', statements: 'Statements', menu: 'Menu', back: 'Back', refresh: 'Refresh',
            sessionsTitle: 'Closed sessions to collect', noSessions: 'All closed sessions are collected ✅',
            collectAll: 'Collect all', otherAmount: 'Other amount', collectOther: 'Collect this amount',
            otherHint: 'The rest goes to the accountant to explain (left in till, loss...).',
            amount: 'Amount', category: 'Category', note: 'Note (optional)', photos: 'Receipt photos',
            save: 'Save', saving: 'Saving…', addPhoto: 'Add photo',
            expenseHint: 'Taken from your balance now; the accountant reviews it.',
            tookHint: 'Cash for yourself (owner drawings), not a business expense.',
            depositTo: 'Deposit to', bank: 'Bank', till: 'POS till',
            countHint: 'Type how much cash you hold now. Any difference goes to the accountant.', counted: 'Counted cash',
            check: 'Check', noMoves: 'No movements yet.', noStatements: 'No statements yet.',
            stOpening: 'Opening balance', stCollected: 'Collected', stSpent: 'Spent', stTook: 'Took for me',
            stDeposited: 'Deposited', stAdjusted: 'Adjustments', stClosing: 'Closing balance',
            correct: '✅ Correct', notCorrect: '⚠️ Not correct', whatsWrong: "What's wrong? (optional)",
            stDraft: 'New', stSent: 'Waiting for you', stConfirmed: 'Confirmed', stDisputed: 'Disputed',
            pendingStatement: 'A statement waits for your answer', openIt: 'Tap to review',
            done: 'Done', home: 'Home', newBalance: 'New balance',
            collected: (a, s) => `Collected ${a} from ${s}`,
            expenseDone: (a, c) => `Expense ${a} (${c}) recorded · waiting for accountant review`,
            tookDone: (a) => `Took ${a} for you`,
            depositDone: (a, t) => `Deposited ${a} to the ${t}`,
            countOk: (a) => `${a} — it matches the books ✅`,
            countDiff: (a, e, d) => `You counted ${a}, the books say ${e} (difference ${d}). The accountant will check it.`,
            stThanks: 'Thank you, statement confirmed.', stNoted: 'Noted. The accountant will check the statement with you.',
            alreadySaved: 'Already saved ✅',
            offline: 'No internet — nothing is saved until the connection is back.',
            network: 'Connection lost. Not sure it was saved: tap Save again, it will not be recorded twice.',
            serverError: 'Server error. Try again.',
            needAmount: 'Enter the amount.', needCategory: 'Choose a category.',
            language: 'العربية', install: 'Install app', iosInstall: 'In Safari: Share button, then "Add to Home Screen".',
            switchBox: 'Switch cash box', logout: 'Log out', confirmCollect: (a, s) => `Collect ${a} from ${s}?`,
            confirm: 'Confirm', cancel: 'Cancel', waitingReview: 'In review', closedAt: 'Closed',
            types: { collect: 'Collected', expense: 'Expense', drawing: 'Took for me', deposit: 'Deposit', adjust: 'Adjustment' },
            telegramToo: 'The app works alongside the Telegram bot: what you record here shows there too.',
            poweredBy: 'Powered by', developedBy: 'Developed by', developer: 'Yousif Shakir',
        },
    };

    const store = {
        get(key) { try { return window.localStorage.getItem('ecc_owner_' + key); } catch (e) { return null; } },
        set(key, value) { try { window.localStorage.setItem('ecc_owner_' + key, value); } catch (e) { /* private mode */ } },
    };

    let lang = store.get('lang') || 'ar';
    const t = (key, ...args) => {
        const value = (I18N[lang] || I18N.ar)[key];
        return typeof value === 'function' ? value(...args) : (value === undefined ? key : value);
    };

    // ------------------------------------------------------------------ state
    const state = {
        user: null, boxes: [], boxId: null, card: null, sessions: [], pending: 0,
        categories: null, form: {}, installEvent: null,
    };
    const $app = document.getElementById('app');
    const $sheet = document.getElementById('sheet');
    const $backdrop = document.getElementById('sheet-backdrop');
    const $toast = document.getElementById('toast');
    const $offline = document.getElementById('offline');

    const esc = (value) => String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

    const newUid = () => {
        const bytes = new Uint8Array(16);
        (window.crypto || window.msCrypto).getRandomValues(bytes);
        return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    };

    // ------------------------------------------------------------------ money
    const decimals = () => (state.card && Number.isInteger(state.card.decimals) ? state.card.decimals : 0);
    const symbol = () => (state.card && (state.card.currency_symbol || state.card.currency)) || '';
    const number = (value) => new Intl.NumberFormat('en-US', {
        minimumFractionDigits: decimals(), maximumFractionDigits: decimals(),
    }).format(Math.abs(Number(value) || 0));
    const money = (value) => `${Number(value) < 0 ? '−' : ''}${number(value)} ${symbol()}`.trim();

    const normalizeDigits = (text) => String(text || '')
        .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
        .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06F0));
    const parseAmount = (text) => {
        let clean = normalizeDigits(text).replace(/[\s,٬،]/g, '').replace(/٫/g, '.');
        clean = clean.replace(/[^0-9.]/g, '');
        if (!clean || clean === '.') {
            return null;
        }
        const value = parseFloat(clean);
        return Number.isFinite(value) ? value : null;
    };
    const formatTyping = (input) => {
        const raw = normalizeDigits(input.value).replace(/[^0-9.]/g, '');
        if (!raw) {
            input.value = '';
            return;
        }
        const [whole, ...rest] = raw.split('.');
        const grouped = (whole || '0').replace(/^0+(?=\d)/, '').replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        input.value = decimals() && rest.length ? `${grouped}.${rest.join('').slice(0, decimals())}` : grouped;
    };

    // ------------------------------------------------------------------ server
    async function api(action, params, timeoutMs) {
        const controller = window.AbortController ? new AbortController() : null;
        const timer = controller ? setTimeout(() => controller.abort(), timeoutMs || 30000) : null;
        let response;
        try {
            response = await fetch(`/ecc/owner/api/${action}`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: params || {}, id: Date.now() }),
                signal: controller ? controller.signal : undefined,
            });
        } catch (e) {
            throw { code: 'network', message: t('network') };
        } finally {
            if (timer) {
                clearTimeout(timer);
            }
        }
        let data;
        try {
            data = await response.json();
        } catch (e) {
            throw { code: response.status >= 500 ? 'server' : 'network', message: t(response.status >= 500 ? 'serverError' : 'network') };
        }
        if (data.error) {
            const message = (data.error.data && data.error.data.message) || data.error.message;
            throw { code: 'server', message: message || t('serverError') };
        }
        const result = data.result || {};
        if (result.ok === false) {
            if (result.code === 'login') {
                state.user = null;
                renderLogin();
            }
            throw { code: result.code, message: result.error };
        }
        return result;
    }

    // ------------------------------------------------------------------ ui helpers
    let toastTimer = null;
    function toast(text, kind) {
        $toast.textContent = text;
        $toast.className = `toast ${kind || ''}`;
        $toast.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { $toast.hidden = true; }, 4500);
    }

    function openSheet(html) {
        $sheet.innerHTML = html;
        $sheet.hidden = false;
        $backdrop.hidden = false;
        const focus = $sheet.querySelector('[autofocus]');
        if (focus) {
            setTimeout(() => focus.focus(), 50);
        }
    }
    function closeSheet() {
        $sheet.hidden = true;
        $backdrop.hidden = true;
        $sheet.innerHTML = '';
    }
    $backdrop.addEventListener('click', closeSheet);

    function applyLang() {
        document.documentElement.lang = lang;
        document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
        document.title = t('appName');
    }

    const companyLogo = (companyId) => `/web/binary/company_logo${companyId ? `?company=${encodeURIComponent(companyId)}` : ''}`;

    function credit() {
        return `<footer class="credit"><img src="${esc(assetUrl('donialink-logo-white.png'))}" alt="DoniaLink">
            ${esc(t('poweredBy'))} <b>DoniaLink</b> · ${esc(t('developedBy'))} <b>${esc(t('developer'))}</b></footer>`;
    }

    function topbar(title, sub, withBack, logoCompanyId) {
        const logo = logoCompanyId
            ? `<img class="company-logo" src="${esc(companyLogo(logoCompanyId))}" alt="" onerror="this.remove()">` : '';
        const left = withBack
            ? `<button class="icon-btn" data-go="home" aria-label="${esc(t('back'))}"><span class="flip">←</span></button>`
            : `<button class="icon-btn" data-act="menu" aria-label="${esc(t('menu'))}">☰</button>`;
        return `<header class="topbar">${left}${logo}<h1>${esc(title)}${sub ? `<span class="sub">${esc(sub)}</span>` : ''}</h1>
            <button class="icon-btn" data-act="refresh" aria-label="${esc(t('refresh'))}">⟳</button></header>`;
    }

    function setBusy(button, busy) {
        if (!button) {
            return;
        }
        button.disabled = busy;
        if (busy) {
            button.dataset.label = button.textContent;
            button.textContent = t('saving');
        } else if (button.dataset.label) {
            button.textContent = button.dataset.label;
        }
    }

    function showError(container, message) {
        const box = container.querySelector('.error') || document.createElement('div');
        box.className = 'error';
        box.textContent = message;
        if (!box.parentNode) {
            container.appendChild(box);
        }
    }

    // ------------------------------------------------------------------ boot / login
    async function boot() {
        applyLang();
        try {
            const info = await api('session');
            if (!info.logged) {
                renderLogin(info.db === false);
                return;
            }
            setUser(info);
            await loadHome();
        } catch (e) {
            if (e.code === 'login') {
                return;
            }
            $app.innerHTML = `<div class="empty">${esc(e.message || t('serverError'))}</div>
                <button class="btn" data-act="reload">${esc(t('refresh'))}</button>`;
        }
    }

    function setUser(info) {
        state.user = info.user;
        state.boxes = info.boxes || [];
        if (!lang || !store.get('lang')) {
            lang = info.lang === 'en' ? 'en' : 'ar';
            applyLang();
        }
        const saved = parseInt(store.get('box') || '0', 10);
        const box = state.boxes.find((b) => b.box_id === saved) || state.boxes[0];
        state.boxId = box ? box.box_id : null;
        state.card = box || null;
        state.categories = null;
    }

    function renderLogin(noDb) {
        applyLang();
        $app.innerHTML = `
            <img class="login-logo" src="${esc(companyLogo())}" alt="" onerror="this.onerror=null;this.src='${esc(assetUrl('icon-192.png'))}'">
            <h1 class="center" style="margin:0 0 4px">${esc(t('appName'))}</h1>
            <p class="center muted" style="margin:0 0 18px">${esc(t('loginHint'))}</p>
            <form class="card" id="login-form" autocomplete="on">
                <label class="lbl" for="login">${esc(t('user'))}</label>
                <input class="input" id="login" name="username" autocomplete="username" autocapitalize="none" required>
                <label class="lbl" for="password">${esc(t('password'))}</label>
                <input class="input" id="password" name="password" type="password" autocomplete="current-password" required>
                <button class="btn" type="submit">${esc(t('enter'))}</button>
                ${noDb ? `<div class="error"><a href="/web/login?redirect=/ecc/owner/app">/web/login</a></div>` : ''}
            </form>
            <p class="center" style="margin-top:16px"><button class="chip" data-act="lang">${esc(t('language'))}</button></p>
            ${credit()}`;
        const form = document.getElementById('login-form');
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const button = form.querySelector('button[type=submit]');
            setBusy(button, true);
            try {
                const info = await api('login', { login: form.login.value, password: form.password.value });
                setUser(info);
                await loadHome();
            } catch (e) {
                showError(form, e.message || t('serverError'));
            } finally {
                setBusy(button, false);
            }
        });
    }

    function assetUrl(name) {
        const css = document.querySelector('link[rel=stylesheet]');
        const base = css ? css.getAttribute('href').replace(/\/app\.css.*$/, '') : '';
        return `${base}/${name}`;
    }

    // ------------------------------------------------------------------ home
    async function loadHome(silent) {
        if (!state.boxId) {
            $app.innerHTML = `${topbar(t('appName'))}<div class="empty">${esc(t('none'))}</div>`;
            return;
        }
        if (!silent && !state.card) {
            $app.innerHTML = '<div class="splash"><div class="spinner"></div></div>';
        }
        try {
            const data = await api('home', { box_id: state.boxId });
            state.card = data.card;
            state.sessions = data.sessions || [];
            state.pending = data.pending_statements || 0;
        } catch (e) {
            if (e.code === 'login') {
                return;
            }
            toast(e.message || t('serverError'), 'bad');
        }
        const name = (location.hash || '#home').slice(1);
        if (name === 'home' || !ROUTES[name]) {
            renderHome();
        } else if (!silent) {
            route();
        }
    }

    function renderHome() {
        const card = state.card;
        if (!card) {
            return;
        }
        const owes = card.balance < 0
            ? `<div class="owes">${esc(t('owes'))} <b dir="ltr">${esc(money(-card.balance))}</b></div>` : '';
        const sessions = state.sessions.slice(0, 3).map(sessionRow).join('');
        $app.innerHTML = `
            ${topbar(card.owner, card.company, false, card.company_id)}
            <section class="balance">
                <div class="label">${esc(t('balance'))}</div>
                <div class="amount">${esc(money(card.balance))}</div>
                ${owes}
                <div class="meta"><span>${esc(t('toCollect'))}: <b>${card.uncollected_sessions}</b></span>
                    <span dir="ltr">${esc(card.uncollected_sessions ? money(card.uncollected_amount) : '')}</span></div>
            </section>
            ${state.pending ? `<button class="banner warn" data-go="statements">📄<span><strong>${esc(t('pendingStatement'))}</strong>${esc(t('openIt'))}</span></button>` : ''}
            <nav class="grid">
                ${tile('collect', '💰', t('collect'), card.uncollected_sessions)}
                ${tile('expense', '🧾', t('expense'))}
                ${tile('took', '👛', t('took'))}
                ${tile('deposit', '🏦', t('deposit'))}
                ${tile('count', '🔢', t('count'))}
                ${tile('moves', '📜', t('moves'))}
                ${tile('statements', '📄', t('statements'), state.pending)}
            </nav>
            <h2 class="section">${esc(t('sessionsTitle'))}</h2>
            <div class="list">${sessions || `<div class="empty">${esc(t('noSessions'))}</div>`}
                ${state.sessions.length > 3 ? `<button class="row" data-go="collect"><span class="main title">+${state.sessions.length - 3}</span><span class="flip">←</span></button>` : ''}</div>
            <p class="hint center" style="margin-top:18px">${esc(t('telegramToo'))}</p>
            ${credit()}`;
    }

    const tile = (route, icon, label, badge) => `<button class="action" data-go="${route}">
        <span class="ico" aria-hidden="true">${icon}</span><span class="t">${esc(label)}</span>
        ${badge ? `<span class="badge">${badge}</span>` : ''}</button>`;

    const sessionRow = (s) => `<button class="row" data-act="session" data-id="${s.session_id}">
        <span class="main"><span class="title">${esc(s.name)}</span>
        <span class="desc">${esc(s.pos)} · ${esc(t('closedAt'))} <span dir="ltr">${esc(s.closed_at || '')}</span>${s.state === 'partial' ? ' <span class="pill warn">½</span>' : ''}</span></span>
        <span class="num in">${esc(money(s.amount))}</span></button>`;

    // ------------------------------------------------------------------ collect
    function renderCollect() {
        $app.innerHTML = `${topbar(t('collect'), state.card && state.card.owner, true)}
            <div class="list">${state.sessions.map(sessionRow).join('') || `<div class="empty">${esc(t('noSessions'))}</div>`}</div>`;
    }

    function openSession(id) {
        const session = state.sessions.find((s) => s.session_id === id);
        if (!session) {
            return;
        }
        const uid = newUid();
        openSheet(`<h3>${esc(session.name)}</h3><p class="muted" style="margin:0 0 8px">${esc(session.pos)} · <span dir="ltr">${esc(session.closed_at || '')}</span></p>
            <button class="btn" data-act="collect-all">${esc(t('collectAll'))} · <span dir="ltr">${esc(money(session.amount))}</span></button>
            <label class="lbl" for="other">${esc(t('otherAmount'))}</label>
            <input class="input money" id="other" inputmode="decimal" autocomplete="off" placeholder="0">
            <p class="hint">${esc(t('otherHint'))}</p>
            <button class="btn secondary" data-act="collect-other">${esc(t('collectOther'))}</button>
            <button class="btn secondary" data-act="close-sheet">${esc(t('cancel'))}</button>`);
        const input = $sheet.querySelector('#other');
        input.addEventListener('input', () => formatTyping(input));
        const run = async (button, amount) => {
            setBusy(button, true);
            try {
                const result = await api('collect', { box_id: state.boxId, session_id: id, amount, request_uid: uid });
                closeSheet();
                const done = result.replayed ? t('alreadySaved') : t('collected', money(amount === null ? session.amount : amount), session.name);
                finish(result, done);
            } catch (e) {
                showError($sheet, e.message || t('serverError'));
            } finally {
                setBusy(button, false);
            }
        };
        $sheet.querySelector('[data-act=collect-all]').addEventListener('click', (ev) => run(ev.currentTarget, null));
        $sheet.querySelector('[data-act=collect-other]').addEventListener('click', (ev) => {
            const amount = parseAmount(input.value);
            if (!amount) {
                showError($sheet, t('needAmount'));
                return;
            }
            run(ev.currentTarget, amount);
        });
    }

    // ------------------------------------------------------------------ forms
    function amountField(id, label) {
        return `<label class="lbl" for="${id}">${esc(label || t('amount'))}</label>
            <input class="input money" id="${id}" inputmode="decimal" autocomplete="off" placeholder="0" autofocus>`;
    }

    function startForm(kind) {
        state.form = { kind, uid: newUid(), photos: [], category: null, target: null };
    }

    async function renderExpense() {
        startForm('expense');
        $app.innerHTML = `${topbar(t('expense'), state.card && state.card.owner, true)}
            <form class="card" id="form">
                ${amountField('amount')}
                <label class="lbl">${esc(t('category'))}</label>
                <div class="chips" id="cats"><div class="spinner"></div></div>
                <label class="lbl">${esc(t('photos'))}</label>
                <div class="photos" id="photos"></div>
                <input type="file" id="file" accept="image/*" capture="environment" hidden>
                <label class="lbl" for="note">${esc(t('note'))}</label>
                <textarea class="input" id="note" maxlength="500"></textarea>
                <p class="hint">${esc(t('expenseHint'))}</p>
                <button class="btn" type="submit">${esc(t('save'))}</button>
            </form>`;
        bindAmount();
        drawPhotos();
        const file = document.getElementById('file');
        file.addEventListener('change', async () => {
            const picked = Array.from(file.files || []);
            file.value = '';
            for (const item of picked) {
                if (state.form.photos.length >= 5) {
                    break;
                }
                try {
                    state.form.photos.push(await compress(item));
                } catch (e) {
                    toast(e.message || 'photo', 'bad');
                }
            }
            drawPhotos();
        });
        try {
            if (!state.categories) {
                state.categories = (await api('categories', { box_id: state.boxId })).categories || [];
            }
        } catch (e) {
            state.categories = [];
            toast(e.message || t('serverError'), 'bad');
        }
        const cats = document.getElementById('cats');
        if (cats) {
            cats.innerHTML = state.categories.map((c) =>
                `<button type="button" class="chip" data-cat="${c.id}" aria-pressed="false">${esc(c.name)}</button>`).join('');
        }
        bindSubmit(async () => {
            const amount = parseAmount(document.getElementById('amount').value);
            if (!amount) {
                throw { message: t('needAmount') };
            }
            if (!state.form.category) {
                throw { message: t('needCategory') };
            }
            const category = state.categories.find((c) => c.id === state.form.category);
            const result = await api('expense', {
                box_id: state.boxId, amount, category_id: state.form.category,
                note: document.getElementById('note').value, request_uid: state.form.uid,
                photos: state.form.photos.map((p) => ({ content_b64: p.b64, mimetype: 'image/jpeg', filename: p.name })),
            }, 90000);
            return [result, result.replayed ? t('alreadySaved') : t('expenseDone', money(amount), category ? category.name : '')];
        });
    }

    function drawPhotos() {
        const box = document.getElementById('photos');
        if (!box) {
            return;
        }
        box.innerHTML = state.form.photos.map((p, i) => `<div class="photo"><img src="data:image/jpeg;base64,${p.b64}" alt="">
            <button type="button" data-del-photo="${i}" aria-label="x">×</button></div>`).join('')
            + (state.form.photos.length < 5 ? `<button type="button" class="add-photo" data-act="add-photo" aria-label="${esc(t('addPhoto'))}">📷</button>` : '');
    }

    function compress(file) {
        // phones take 4-12 MB photos: send a 1600 px JPEG instead (fast on a weak connection)
        return new Promise((resolve, reject) => {
            const url = URL.createObjectURL(file);
            const img = new Image();
            img.onload = () => {
                const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
                const canvas = document.createElement('canvas');
                canvas.width = Math.round(img.width * scale);
                canvas.height = Math.round(img.height * scale);
                canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
                URL.revokeObjectURL(url);
                const data = canvas.toDataURL('image/jpeg', 0.78);
                resolve({ b64: data.split(',')[1], name: (file.name || 'receipt').replace(/\.[^.]+$/, '') + '.jpg' });
            };
            img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('photo')); };
            img.src = url;
        });
    }

    function renderTook() {
        startForm('took');
        $app.innerHTML = `${topbar(t('took'), state.card && state.card.owner, true)}
            <form class="card" id="form">${amountField('amount')}
                <label class="lbl" for="note">${esc(t('note'))}</label><textarea class="input" id="note" maxlength="500"></textarea>
                <p class="hint">${esc(t('tookHint'))}</p>
                <button class="btn" type="submit">${esc(t('save'))}</button></form>`;
        bindAmount();
        bindSubmit(async () => {
            const amount = parseAmount(document.getElementById('amount').value);
            if (!amount) {
                throw { message: t('needAmount') };
            }
            const result = await api('took', { box_id: state.boxId, amount, note: document.getElementById('note').value,
                request_uid: state.form.uid });
            return [result, result.replayed ? t('alreadySaved') : t('tookDone', money(amount))];
        });
    }

    function renderDeposit() {
        startForm('deposit');
        const card = state.card || {};
        state.form.target = 'bank';
        $app.innerHTML = `${topbar(t('deposit'), card.owner, true)}
            <form class="card" id="form">${amountField('amount')}
                <label class="lbl">${esc(t('depositTo'))}</label>
                <div class="seg">
                    <button type="button" class="chip" data-target="bank" aria-pressed="true">🏦 ${esc(card.bank_name || t('bank'))}</button>
                    <button type="button" class="chip" data-target="till" aria-pressed="false" ${card.till_available ? '' : 'disabled'}>🧮 ${esc(card.till_name || t('till'))}</button>
                </div>
                <label class="lbl" for="note">${esc(t('note'))}</label><textarea class="input" id="note" maxlength="500"></textarea>
                <button class="btn" type="submit">${esc(t('save'))}</button></form>`;
        bindAmount();
        bindSubmit(async () => {
            const amount = parseAmount(document.getElementById('amount').value);
            if (!amount) {
                throw { message: t('needAmount') };
            }
            const target = state.form.target;
            const result = await api('deposit', { box_id: state.boxId, amount, target,
                note: document.getElementById('note').value, request_uid: state.form.uid });
            const name = target === 'bank' ? (card.bank_name || t('bank')) : (card.till_name || t('till'));
            return [result, result.replayed ? t('alreadySaved') : t('depositDone', money(amount), name)];
        });
    }

    function renderCount() {
        startForm('count');
        $app.innerHTML = `${topbar(t('count'), state.card && state.card.owner, true)}
            <form class="card" id="form">${amountField('amount', t('counted'))}
                <p class="hint">${esc(t('countHint'))}</p>
                <button class="btn" type="submit">${esc(t('check'))}</button></form>`;
        bindAmount();
        bindSubmit(async () => {
            const raw = document.getElementById('amount').value;
            const counted = parseAmount(raw);
            if (counted === null) {
                throw { message: t('needAmount') };
            }
            const result = await api('count', { box_id: state.boxId, counted });
            const text = result.difference
                ? t('countDiff', money(counted), money(result.expected), money(result.difference))
                : t('countOk', money(counted));
            return [result, text];
        });
    }

    function bindAmount() {
        const input = document.getElementById('amount');
        if (input) {
            input.addEventListener('input', () => formatTyping(input));
        }
    }

    function bindSubmit(handler) {
        const form = document.getElementById('form');
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const button = form.querySelector('button[type=submit]');
            if (button.disabled) {
                return;
            }
            setBusy(button, true);
            try {
                const [result, text] = await handler();
                finish(result, text);
            } catch (e) {
                // keep the same request id: Save again cannot record it twice
                showError(form, e.message || t('serverError'));
            } finally {
                setBusy(button, false);
            }
        });
    }

    function finish(result, text) {
        if (result.card) {
            state.card = result.card;
        }
        if (result.sessions) {
            state.sessions = result.sessions;
        }
        state.form = {};
        $app.innerHTML = `${topbar(t('done'), state.card && state.card.owner, true)}
            <div class="card center"><div class="done-ico">✅</div><p style="font-size:17px">${esc(text)}</p>
            <p class="muted">${esc(t('newBalance'))}: <b dir="ltr">${esc(money(state.card ? state.card.balance : 0))}</b></p>
            <button class="btn" data-go="home">${esc(t('home'))}</button></div>`;
        toast(text, 'ok');
        if (navigator.vibrate) {
            navigator.vibrate(30);
        }
        loadHome(true);
    }

    // ------------------------------------------------------------------ history / statements
    async function renderMoves() {
        $app.innerHTML = `${topbar(t('moves'), state.card && state.card.owner, true)}<div class="list" id="moves"><div class="splash" style="min-height:30vh"><div class="spinner"></div></div></div>`;
        try {
            const data = await api('moves', { box_id: state.boxId, limit: 50 });
            state.card = data.card || state.card;
            const list = document.getElementById('moves');
            if (!list) {
                return;
            }
            list.innerHTML = (data.moves || []).map((m) => `<div class="row">
                <span class="main"><span class="title">${esc((t('types')[m.type]) || m.type_label)}${m.review === 'to_review' ? ` <span class="pill warn">${esc(t('waitingReview'))}</span>` : ''}</span>
                <span class="desc">${esc(m.description)}</span><span class="small"><bdi dir="ltr">${esc(m.local_date)}</bdi></span></span>
                <span class="side"><span class="num ${m.amount >= 0 ? 'in' : 'out'}">${m.amount >= 0 ? '+' : ''}${esc(money(m.amount))}</span>
                <span class="small" style="display:block">→ ${esc(money(m.balance_after))}</span></span></div>`).join('')
                || `<div class="empty">${esc(t('noMoves'))}</div>`;
        } catch (e) {
            if (e.code !== 'login') {
                toast(e.message || t('serverError'), 'bad');
            }
        }
    }

    const FIG_LABELS = { opening: 'stOpening', collected: 'stCollected', spent: 'stSpent', took: 'stTook',
        deposited: 'stDeposited', adjusted: 'stAdjusted', closing: 'stClosing' };
    const ST_STATES = { draft: 'stDraft', sent: 'stSent', confirmed: 'stConfirmed', disputed: 'stDisputed' };

    async function renderStatements() {
        $app.innerHTML = `${topbar(t('statements'), state.card && state.card.owner, true)}<div id="sts"><div class="splash" style="min-height:30vh"><div class="spinner"></div></div></div>`;
        try {
            const data = await api('statements', { box_id: state.boxId });
            drawStatements(data.statements || []);
        } catch (e) {
            if (e.code !== 'login') {
                toast(e.message || t('serverError'), 'bad');
            }
        }
    }

    function drawStatements(statements) {
        const box = document.getElementById('sts');
        if (!box) {
            return;
        }
        box.innerHTML = statements.map((s) => {
            const figs = s.figures.filter(([key, value]) => key !== 'adjusted' || value).map(([key, value]) => {
                const sign = { collected: '+', spent: '−', took: '−', deposited: '−' }[key] || '';
                const cls = key === 'closing' ? ' total' : '';
                const shown = sign ? `${sign}${number(value)} ${symbol()}` : money(value);
                return `<span class="${cls}">${esc(t(FIG_LABELS[key]))}</span><span class="v${cls}">${esc(shown)}</span>`;
            }).join('');
            const owes = s.closing < 0 ? `<p class="hint">${esc(t('owes'))} <b dir="ltr">${esc(money(-s.closing))}</b></p>` : '';
            const answer = s.can_answer ? `<label class="lbl" for="note-${s.id}">${esc(t('whatsWrong'))}</label>
                <textarea class="input" id="note-${s.id}" maxlength="500"></textarea>
                <div class="btn-row"><button class="btn" data-answer="1" data-id="${s.id}">${esc(t('correct'))}</button>
                <button class="btn danger" data-answer="0" data-id="${s.id}">${esc(t('notCorrect'))}</button></div>`
                : (s.answer_note ? `<p class="hint">${esc(s.answer_note)}</p>` : '');
            return `<div class="card" style="margin-bottom:12px" id="st-${s.id}">
                <div style="display:flex;justify-content:space-between;gap:8px;margin-bottom:10px"><b dir="ltr">${esc(s.date_from)} → ${esc(s.date_to)}</b>
                <span class="pill ${s.can_answer ? 'warn' : ''}">${esc(t(ST_STATES[s.state] || s.state))}</span></div>
                <div class="figs">${figs}</div>${owes}${answer}</div>`;
        }).join('') || `<div class="list"><div class="empty">${esc(t('noStatements'))}</div></div>`;
    }

    async function answerStatement(button) {
        const id = parseInt(button.dataset.id, 10);
        const correct = button.dataset.answer === '1';
        const note = (document.getElementById(`note-${id}`) || {}).value || '';
        const card = document.getElementById(`st-${id}`);
        setBusy(button, true);
        try {
            const result = await api('statement_answer', { box_id: state.boxId, statement_id: id, correct, note });
            state.pending = Math.max(0, state.pending - 1);
            toast(correct ? t('stThanks') : t('stNoted'), 'ok');
            drawStatements(result.statements || []);
        } catch (e) {
            showError(card, e.message || t('serverError'));
            setBusy(button, false);
        }
    }

    // ------------------------------------------------------------------ menu
    function openMenu() {
        const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
        const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
        const boxes = state.boxes.length > 1 ? `<h3 style="margin-top:6px">${esc(t('switchBox'))}</h3><div class="list">${state.boxes.map((b) =>
            `<button class="row" data-box="${b.box_id}"><span class="main"><span class="title">${esc(b.owner)}</span><span class="desc">${esc(b.company)}</span></span>${b.box_id === state.boxId ? '✓' : ''}</button>`).join('')}</div>` : '';
        let install = '';
        if (!standalone && state.installEvent) {
            install = `<button class="btn" data-act="install">📲 ${esc(t('install'))}</button>`;
        } else if (!standalone && isIos) {
            install = `<p class="hint">📲 ${esc(t('iosInstall'))}</p>`;
        }
        openSheet(`<h3>${esc(state.user || t('appName'))}</h3>${boxes}${install}
            <button class="btn secondary" data-act="lang">🌐 ${esc(t('language'))}</button>
            <button class="btn secondary" data-act="logout">${esc(t('logout'))}</button>
            <button class="btn secondary" data-act="close-sheet">${esc(t('cancel'))}</button>${credit()}`);
    }

    // ------------------------------------------------------------------ routing
    const ROUTES = {
        home: renderHome, collect: renderCollect, expense: renderExpense, took: renderTook,
        deposit: renderDeposit, count: renderCount, moves: renderMoves, statements: renderStatements,
    };

    function route() {
        if (!state.user) {
            return;
        }
        closeSheet();
        const name = (location.hash || '#home').slice(1);
        (ROUTES[name] || renderHome)();
        window.scrollTo(0, 0);
    }

    function go(name) {
        if ((location.hash || '#home') === `#${name}`) {
            route();
        } else {
            location.hash = name;
        }
    }

    window.addEventListener('hashchange', route);

    document.addEventListener('click', async (event) => {
        const target = event.target.closest('[data-go],[data-act],[data-cat],[data-target],[data-box],[data-answer],[data-del-photo]');
        if (!target) {
            return;
        }
        if (target.dataset.go) {
            event.preventDefault();
            go(target.dataset.go);
            return;
        }
        if (target.dataset.cat) {
            state.form.category = parseInt(target.dataset.cat, 10);
            target.parentNode.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', String(c === target)));
            return;
        }
        if (target.dataset.target) {
            if (target.disabled) {
                return;
            }
            state.form.target = target.dataset.target;
            target.parentNode.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', String(c === target)));
            return;
        }
        if (target.dataset.box) {
            state.boxId = parseInt(target.dataset.box, 10);
            store.set('box', String(state.boxId));
            state.card = state.boxes.find((b) => b.box_id === state.boxId) || null;
            state.categories = null;
            closeSheet();
            go('home');
            loadHome();
            return;
        }
        if (target.dataset.answer !== undefined) {
            answerStatement(target);
            return;
        }
        if (target.dataset.delPhoto !== undefined) {
            state.form.photos.splice(parseInt(target.dataset.delPhoto, 10), 1);
            drawPhotos();
            return;
        }
        switch (target.dataset.act) {
            case 'menu': openMenu(); break;
            case 'close-sheet': closeSheet(); break;
            case 'reload': window.location.reload(); break;
            case 'refresh': {
                const name = (location.hash || '#home').slice(1);
                if (name === 'home' || !ROUTES[name]) {
                    await loadHome();
                } else if (name === 'moves' || name === 'statements' || name === 'collect') {
                    if (name === 'collect') {
                        await loadHome(true);
                    }
                    route();
                }
                break;
            }
            case 'session': openSession(parseInt(target.dataset.id, 10)); break;
            case 'add-photo': document.getElementById('file').click(); break;
            case 'lang':
                lang = lang === 'ar' ? 'en' : 'ar';
                store.set('lang', lang);
                applyLang();
                closeSheet();
                if (state.user) {
                    route();
                } else {
                    renderLogin();
                }
                break;
            case 'install':
                if (state.installEvent) {
                    state.installEvent.prompt();
                    state.installEvent = null;
                }
                closeSheet();
                break;
            case 'logout':
                try { await api('logout'); } catch (e) { /* already out */ }
                state.user = null;
                closeSheet();
                location.hash = '';
                renderLogin();
                break;
            default: break;
        }
    });

    // ------------------------------------------------------------------ platform
    window.addEventListener('beforeinstallprompt', (event) => {
        event.preventDefault();
        state.installEvent = event;
    });
    const updateOnline = () => {
        $offline.hidden = navigator.onLine;
        $offline.textContent = t('offline');
    };
    window.addEventListener('online', () => { updateOnline(); if (state.user) { loadHome(true); } });
    window.addEventListener('offline', updateOnline);
    document.addEventListener('visibilitychange', () => {
        // back to the app: a session may have closed meanwhile
        if (document.visibilityState === 'visible' && state.user && (location.hash || '#home') === '#home') {
            loadHome(true);
        }
    });
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/ecc/owner/sw.js', { scope: '/ecc/owner/' }).catch(() => { /* http without TLS */ });
    }
    updateOnline();
    boot();
}());
