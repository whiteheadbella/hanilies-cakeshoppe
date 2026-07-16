(function () {
    const panel = document.getElementById('demoControlPanel');
    if (!panel) {
        return;
    }

    const startEndpoint = panel.dataset.demoStartUrl;
    const statusEndpoint = panel.dataset.demoStatusUrl;
    const stopEndpoint = panel.dataset.demoStopUrl;
    const csrfTokenInput = panel.querySelector('input[name="csrfmiddlewaretoken"]');
    const statusNode = document.getElementById('demo-status');
    const startButtons = Array.from(panel.querySelectorAll('.demo-trigger'));
    const customButton = document.getElementById('demo-custom-script-trigger');
    const stopButton = document.getElementById('demo-stop-trigger');
    const delaySelect = document.getElementById('demo-delay');
    const scriptSteps = Array.from(panel.querySelectorAll('.demo-script-step'));
    const STORAGE_KEY = 'haniliesDemoBotV2';
    const DEMO_FILE_BASE64 = 'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFUlEQVR4nGP8f+D0fwYGBgYmEAHCADb8A41mH6P1AAAAAElFTkSuQmCC';
    const originalConfirm = window.confirm.bind(window);

    let isLaunching = false;
    let isStopping = false;
    let lastRunningState = false;
    let refreshTimer = null;
    let actionTimer = null;
    let isExecuting = false;

    const stepMessages = {
        intro: 'Opening the guided system introduction...',
        register: 'Completing the customer registration flow...',
        customer_login: 'Logging in with the demo customer account...',
        homepage: 'Walking through the homepage modules...',
        cake_browse: 'Browsing the cakes catalog...',
        cake_customize: 'Completing the cake customization order...',
        package_browse: 'Browsing the packages catalog...',
        package_customize: 'Completing the package customization flow...',
        cart_review: 'Showing the demo cart review...',
        checkout: 'Completing the checkout details...',
        payment: 'Demonstrating the payment proof flow...',
        customer_orders: 'Opening the customer order confirmation view...',
        admin_login: 'Switching to the administrator flow...',
        admin_dashboard: 'Highlighting the administrator dashboard...',
        admin_cake_orders: 'Reviewing the cake order queue...',
        admin_package_orders: 'Reviewing the package order queue...',
        admin_payments: 'Reviewing payment verification...',
        admin_cakes: 'Demonstrating cake product management...',
        admin_packages: 'Demonstrating package management...',
        admin_users: 'Demonstrating user management...',
        audit_trail: 'Opening the audit trail and export tools...',
        admin_logout: 'Logging out and closing the presentation walkthrough...'
    };

    const scenarioLabels = {
        full: 'full demo flow',
        customer: 'customer flow',
        admin: 'administrator flow',
        custom: 'selected-step flow'
    };

    function setStatus(message, state) {
        if (!statusNode) {
            return;
        }
        statusNode.textContent = message;
        statusNode.dataset.state = state || 'idle';
    }

    function setControlState(isRunning) {
        lastRunningState = isRunning;
        const disabled = isRunning || isLaunching || isStopping;
        startButtons.forEach((button) => {
            button.disabled = disabled;
        });
        if (customButton) {
            customButton.disabled = disabled;
        }
        scriptSteps.forEach((step) => {
            step.disabled = disabled;
        });
        if (delaySelect) {
            delaySelect.disabled = disabled;
        }
        if (stopButton) {
            stopButton.disabled = !isRunning || isLaunching || isStopping;
        }
    }

    async function readJsonResponse(response) {
        const text = await response.text();
        try {
            return text ? JSON.parse(text) : {};
        } catch (error) {
            return { ok: false, error: text || 'Unexpected response from the server.' };
        }
    }

    function parseFloatOrDefault(value, fallback) {
        const parsed = Number.parseFloat(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function pace(plan, milliseconds) {
        const selectedDelay = parseFloatOrDefault(plan && plan.delay, 1.15);
        const minimumDelay = selectedDelay <= 0.6 ? 80 : 180;
        return Math.max(minimumDelay, Math.round(selectedDelay * milliseconds));
    }

    function wait(milliseconds) {
        return new Promise((resolve) => {
            window.setTimeout(resolve, milliseconds);
        });
    }

    function runtime(plan) {
        if (!plan.runtime || typeof plan.runtime !== 'object') {
            plan.runtime = {};
        }
        return plan.runtime;
    }

    function attempts(plan) {
        const state = runtime(plan);
        if (!state.attempts || typeof state.attempts !== 'object') {
            state.attempts = {};
        }
        return state.attempts;
    }

    function stepUrl(plan, step) {
        const urls = (plan && plan.step_urls) || {};
        const aliases = {
            intro: 'home',
            homepage: 'home',
            customer_login: 'login',
            admin_login: 'login',
            cake_browse: 'cakes',
            package_browse: 'packages',
            admin_logout: 'logout'
        };
        return urls[step] || urls[aliases[step]] || null;
    }

    function pathFromUrl(url) {
        if (!url) {
            return '';
        }
        try {
            return new URL(url, window.location.origin).pathname;
        } catch (error) {
            return '';
        }
    }

    function matchesTarget(url) {
        if (!url) {
            return false;
        }
        try {
            const target = new URL(url, window.location.origin);
            if (target.pathname !== window.location.pathname) {
                return false;
            }
            if (target.search) {
                return target.search === window.location.search;
            }
            return true;
        } catch (error) {
            return false;
        }
    }

    function currentStep(plan) {
        return Array.isArray(plan && plan.script_steps) ? plan.script_steps[plan.currentIndex || 0] : null;
    }

    function scheduleRun(delay) {
        if (actionTimer) {
            return;
        }
        actionTimer = window.setTimeout(() => {
            actionTimer = null;
            maybeRunBrowserDemo();
        }, delay);
    }

    function clearScheduledRun() {
        if (actionTimer) {
            window.clearTimeout(actionTimer);
            actionTimer = null;
        }
    }

    function savePlan(plan) {
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(plan));
    }

    function loadPlan() {
        try {
            const rawValue = window.sessionStorage.getItem(STORAGE_KEY);
            return rawValue ? JSON.parse(rawValue) : null;
        } catch (error) {
            return null;
        }
    }

    function overlayNode(id, className, tagName) {
        let node = document.getElementById(id);
        if (!node) {
            node = document.createElement(tagName || 'div');
            node.id = id;
            node.className = className;
            document.body.appendChild(node);
        }
        return node;
    }

    function cleanupVisuals() {
        [
            'demo-bot-cursor',
            'demo-bot-cursor-ring',
            'demo-bot-banner',
            'demo-bot-callout',
            'demo-bot-cart',
            'demo-bot-highlight'
        ].forEach((id) => {
            const node = document.getElementById(id);
            if (node) {
                node.remove();
            }
        });
        document.querySelectorAll('.demo-bot-click-ripple').forEach((node) => {
            node.remove();
        });
    }

    function clearPlan() {
        clearScheduledRun();
        window.sessionStorage.removeItem(STORAGE_KEY);
        cleanupVisuals();
        window.confirm = originalConfirm;
    }

    function restoreDemoGuards() {
        const plan = loadPlan();
        if (plan && plan.mode === 'browser') {
            window.confirm = () => true;
            return plan;
        }
        window.confirm = originalConfirm;
        return null;
    }

    async function finishDemo(message) {
        clearScheduledRun();
        window.sessionStorage.removeItem(STORAGE_KEY);
        window.confirm = originalConfirm;
        lastRunningState = false;
        setStatus(message, 'success');
        setControlState(false);
        try {
            await fetch(stopEndpoint, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfTokenInput ? csrfTokenInput.value : '',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
        } catch (error) {
            // Ignore session cleanup errors here.
        }
    }

    function selectedScriptSteps() {
        return scriptSteps.filter((step) => step.checked).map((step) => step.value);
    }

    function selectedPaceValue() {
        return parseFloatOrDefault(delaySelect && delaySelect.value, 1.15);
    }

    function selectedPaceLabel() {
        if (!delaySelect) {
            return 'Normal';
        }
        const selectedOption = delaySelect.options[delaySelect.selectedIndex];
        return selectedOption ? selectedOption.text : 'Normal';
    }

    function payloadForScenario(scenario, customSteps) {
        return {
            scenario,
            script_steps: customSteps,
            delay: selectedPaceValue()
        };
    }

    function buildCustomer(plan) {
        const state = runtime(plan);
        if (state.customer) {
            return state.customer;
        }
        const sample = plan.sample_customer || {};
        const suffix = `${Date.now()}`.slice(-6);
        const firstName = sample.first_name || 'Presentation';
        const lastName = sample.last_name || 'Customer';
        const username = `demo${suffix}`;
        const emailDomain = sample.email_domain || 'example.com';
        state.customer = {
            first_name: firstName,
            last_name: lastName,
            username,
            email: `presentation.${suffix}@${emailDomain}`,
            phone: sample.phone || '09171234567',
            password: sample.password || 'DemoRegister123!'
        };
        savePlan(plan);
        return state.customer;
    }

    function createDemoFile(name) {
        const binary = window.atob(DEMO_FILE_BASE64);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) {
            bytes[index] = binary.charCodeAt(index);
        }
        return new File([bytes], name, { type: 'image/png' });
    }

    function attachDemoFile(input, fileName) {
        if (!input || typeof window.DataTransfer === 'undefined') {
            return false;
        }
        const transfer = new window.DataTransfer();
        transfer.items.add(createDemoFile(fileName));
        input.files = transfer.files;
        input.dispatchEvent(new Event('change', { bubbles: true }));
        input.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
    }

    function dispatchFieldEvents(field) {
        field.dispatchEvent(new Event('input', { bubbles: true }));
        field.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function elementFrom(target) {
        if (!target) {
            return null;
        }
        if (typeof target === 'string') {
            return document.querySelector(target);
        }
        return target;
    }

    function textForElement(element) {
        if (!element) {
            return '';
        }
        const label = element.closest('label');
        return [
            element.value,
            element.dataset.label,
            element.getAttribute('aria-label'),
            element.name,
            label ? label.innerText : '',
            element.innerText
        ].filter(Boolean).join(' ').toLowerCase();
    }

    function findTextMatch(selectors, needles, root) {
        const scope = root || document;
        const terms = (Array.isArray(needles) ? needles : [needles]).map((value) => String(value || '').toLowerCase()).filter(Boolean);
        if (!terms.length) {
            return null;
        }
        return Array.from(scope.querySelectorAll(selectors)).find((element) => {
            const haystack = (element.innerText || element.textContent || '').toLowerCase();
            return terms.some((needle) => haystack.includes(needle));
        }) || null;
    }

    function cartItems(plan) {
        const state = runtime(plan);
        const showcase = plan.showcase_catalog || {};
        const items = [];
        if (showcase.cake_name) {
            items.push({
                title: showcase.cake_name,
                meta: state.cakeSubmitted ? 'Cake order submitted' : 'Cake customization selected'
            });
        }
        if (showcase.package_name) {
            items.push({
                title: showcase.package_name,
                meta: state.packageSubmitted ? 'Package order submitted' : 'Package checkout in progress'
            });
        }
        return items;
    }

    function showBanner(message, theme) {
        const banner = overlayNode('demo-bot-banner', 'demo-bot-banner');
        banner.dataset.state = theme || 'default';
        banner.innerHTML = `<strong>Demo Bot</strong><span>${message}</span>`;
        banner.style.opacity = '1';
        banner.style.transform = 'translateY(0)';
    }

    function showCallout(message, target) {
        const callout = overlayNode('demo-bot-callout', 'demo-bot-callout');
        callout.textContent = message;
        const element = elementFrom(target);
        if (element) {
            const rect = element.getBoundingClientRect();
            callout.style.top = `${Math.max(24, rect.bottom + 12)}px`;
            callout.style.left = `${Math.max(24, Math.min(window.innerWidth - 320, rect.left))}px`;
        } else {
            callout.style.top = '96px';
            callout.style.left = '24px';
        }
        callout.style.opacity = '1';
    }

    function showCart(plan, heading) {
        const items = cartItems(plan);
        const cart = overlayNode('demo-bot-cart', 'demo-bot-cart');
        const list = items.map((item) => `<li><strong>${item.title}</strong><span>${item.meta}</span></li>`).join('');
        cart.innerHTML = `
            <div class="demo-bot-cart__title">${heading || 'Demo Cart Review'}</div>
            <ul>${list || '<li><strong>No demo items yet</strong><span>The walkthrough will add items in the next steps.</span></li>'}</ul>
        `;
        cart.style.opacity = '1';
        cart.style.transform = 'translateY(0)';
    }

    function highlightElement(target) {
        const element = elementFrom(target);
        if (!element) {
            return false;
        }
        const highlight = overlayNode('demo-bot-highlight', 'demo-bot-highlight');
        const rect = element.getBoundingClientRect();
        highlight.style.top = `${window.scrollY + rect.top - 8}px`;
        highlight.style.left = `${window.scrollX + rect.left - 8}px`;
        highlight.style.width = `${rect.width + 16}px`;
        highlight.style.height = `${rect.height + 16}px`;
        highlight.style.opacity = '1';
        return true;
    }

    async function moveCursorTo(target) {
        const cursor = overlayNode('demo-bot-cursor', 'demo-bot-cursor');
        const ring = overlayNode('demo-bot-cursor-ring', 'demo-bot-cursor-ring');
        let x = 36;
        let y = 36;
        const element = elementFrom(target);
        if (element) {
            const rect = element.getBoundingClientRect();
            x = rect.left + (rect.width / 2);
            y = rect.top + (rect.height / 2);
        } else if (target && typeof target.x === 'number' && typeof target.y === 'number') {
            x = target.x;
            y = target.y;
        }
        cursor.style.opacity = '1';
        ring.style.opacity = '1';
        cursor.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
        ring.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
        await wait(320);
    }

    function rippleAt(target) {
        const element = elementFrom(target);
        if (!element) {
            return;
        }
        const rect = element.getBoundingClientRect();
        const ripple = document.createElement('span');
        ripple.className = 'demo-bot-click-ripple';
        ripple.style.left = `${window.scrollX + rect.left + (rect.width / 2)}px`;
        ripple.style.top = `${window.scrollY + rect.top + (rect.height / 2)}px`;
        document.body.appendChild(ripple);
        window.setTimeout(() => ripple.remove(), 800);
    }

    async function clickElement(target, plan) {
        const element = elementFrom(target);
        if (!element) {
            return false;
        }
        try {
            element.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
        } catch (error) {
            element.scrollIntoView();
        }
        await wait(220);
        highlightElement(element);
        await moveCursorTo(element);
        rippleAt(element);
        element.click();
        await wait(pace(plan, 420));
        return true;
    }

    async function typeIntoField(field, value, plan) {
        if (!field) {
            return false;
        }
        try {
            field.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
        } catch (error) {
            field.scrollIntoView();
        }
        highlightElement(field);
        await moveCursorTo(field);
        field.focus();

        if (field.type === 'date' || field.type === 'time') {
            field.value = String(value || '');
            dispatchFieldEvents(field);
            await wait(Math.max(24, Math.round(pace(plan, 120))));
            return true;
        }

        field.value = '';
        dispatchFieldEvents(field);
        for (const character of String(value || '')) {
            field.value += character;
            dispatchFieldEvents(field);
            await wait(Math.max(18, Math.round(pace(plan, 34))));
        }
        return true;
    }

    async function setFieldValue(selector, value, plan) {
        return typeIntoField(document.querySelector(selector), value, plan);
    }

    async function chooseSelect(target, needles, plan) {
        const field = elementFrom(target);
        if (!field || !field.options) {
            return false;
        }
        const terms = (Array.isArray(needles) ? needles : [needles]).map((value) => String(value || '').toLowerCase()).filter(Boolean);
        const option = Array.from(field.options).find((candidate) => {
            const haystack = `${candidate.text} ${candidate.value}`.toLowerCase();
            return terms.some((needle) => haystack.includes(needle));
        }) || Array.from(field.options).find((candidate) => candidate.value) || field.options[0];
        if (!option) {
            return false;
        }
        field.value = option.value;
        dispatchFieldEvents(field);
        highlightElement(field);
        await moveCursorTo(field);
        await wait(pace(plan, 220));
        return true;
    }

    async function chooseInputByName(name, needles, plan, options) {
        const config = options || {};
        const fields = Array.from(document.querySelectorAll(`input[name="${name}"]`));
        if (!fields.length) {
            return false;
        }
        const terms = (Array.isArray(needles) ? needles : [needles]).map((value) => String(value || '').toLowerCase()).filter(Boolean);
        let target = null;
        if (terms.length) {
            target = fields.find((field) => terms.some((needle) => textForElement(field).includes(needle)));
        }
        if (!target && Number.isInteger(config.index) && fields[config.index]) {
            target = fields[config.index];
        }
        if (!target) {
            target = fields[0];
        }
        if (!target) {
            return false;
        }
        if (!target.checked) {
            await clickElement(target, plan);
        }
        target.checked = true;
        dispatchFieldEvents(target);
        return true;
    }

    function submitForm(form) {
        if (!form) {
            return false;
        }
        if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
            return true;
        }
        form.submit();
        return true;
    }

    function retryStep(plan, key, message, maxAttempts) {
        const registry = attempts(plan);
        const nextCount = (registry[key] || 0) + 1;
        registry[key] = nextCount;
        savePlan(plan);
        if (nextCount > (maxAttempts || 10)) {
            throw new Error(message);
        }
        setStatus(message, 'loading');
        scheduleRun(pace(plan, 900));
        return true;
    }

    function resetAttempts(plan, key) {
        const registry = attempts(plan);
        delete registry[key];
        savePlan(plan);
    }

    function advancePlan(plan) {
        const nextIndex = (plan.currentIndex || 0) + 1;
        if (!Array.isArray(plan.script_steps) || nextIndex >= plan.script_steps.length) {
            finishDemo('Demo completed successfully.');
            return;
        }
        plan.currentIndex = nextIndex;
        savePlan(plan);
        const nextStep = currentStep(plan);
        const targetUrl = stepUrl(plan, nextStep);
        if (targetUrl && !matchesTarget(targetUrl)) {
            window.location.assign(targetUrl);
            return;
        }
        scheduleRun(pace(plan, 500));
    }

    async function navigateIfNeeded(plan, step) {
        const targetUrl = stepUrl(plan, step);
        if (targetUrl && !matchesTarget(targetUrl)) {
            savePlan(plan);
            window.location.assign(targetUrl);
            return true;
        }
        return false;
    }

    async function runIntro(plan) {
        if (await navigateIfNeeded(plan, 'intro')) {
            return;
        }
        showBanner(plan.intro_message || 'Welcome to the guided Hanilies Cakeshoppe demo.', 'loading');
        showCallout('The walkthrough starts on the live homepage and will continue automatically.');
        const nav = document.querySelector('header nav, nav.navbar, .navbar');
        if (nav) {
            highlightElement(nav);
            await moveCursorTo(nav);
            await wait(pace(plan, 900));
        }
        const hero = document.querySelector('.hero, .hero-section, .banner-section, main section');
        if (hero) {
            hero.scrollIntoView({ behavior: 'smooth', block: 'start' });
            highlightElement(hero);
            await wait(pace(plan, 1200));
        }
        advancePlan(plan);
    }

    async function runRegister(plan) {
        const state = runtime(plan);
        const customer = buildCustomer(plan);
        const profilePath = pathFromUrl(stepUrl(plan, 'profile'));
        if (state.registerSubmitted && window.location.pathname === profilePath) {
            showBanner('Customer registration completed successfully.', 'success');
            state.registerCompleted = true;
            savePlan(plan);
            await wait(pace(plan, 1200));
            advancePlan(plan);
            return;
        }
        if (await navigateIfNeeded(plan, 'register')) {
            return;
        }
        const form = document.getElementById('registerForm') || document.querySelector('form[action*="/register/"]');
        if (!form) {
            retryStep(plan, 'register-form', 'Waiting for the registration form to finish loading...');
            return;
        }
        resetAttempts(plan, 'register-form');
        showBanner('Registering a demo customer account.', 'loading');
        await typeIntoField(form.querySelector('input[name="firstname"]'), customer.first_name, plan);
        await typeIntoField(form.querySelector('input[name="lastname"]'), customer.last_name, plan);
        await typeIntoField(form.querySelector('input[name="email"]'), customer.email, plan);
        await typeIntoField(form.querySelector('input[name="username"]'), customer.username, plan);
        await typeIntoField(form.querySelector('input[name="password"]'), customer.password, plan);
        await typeIntoField(form.querySelector('input[name="confirm_password"]'), customer.password, plan);
        await typeIntoField(form.querySelector('input[name="phone"]'), customer.phone, plan);
        const terms = form.querySelector('#terms');
        if (terms && !terms.checked) {
            await clickElement(terms, plan);
        }
        state.registerSubmitted = true;
        savePlan(plan);
        submitForm(form);
    }

    async function runCustomerLogin(plan) {
        const state = runtime(plan);
        const customer = buildCustomer(plan);
        const loginPath = pathFromUrl(stepUrl(plan, 'customer_login'));
        if (state.customerLoginSubmitted && window.location.pathname !== loginPath) {
            showBanner('Customer login successful.', 'success');
            await wait(pace(plan, 1100));
            advancePlan(plan);
            return;
        }
        if (!state.customerLogoutStarted && window.location.pathname !== loginPath) {
            state.customerLogoutStarted = true;
            savePlan(plan);
            window.location.assign(stepUrl(plan, 'logout'));
            return;
        }
        if (await navigateIfNeeded(plan, 'customer_login')) {
            return;
        }
        const form = document.querySelector('form[action*="/login/"]');
        if (!form) {
            retryStep(plan, 'customer-login-form', 'Waiting for the customer login form to finish loading...');
            return;
        }
        resetAttempts(plan, 'customer-login-form');
        showBanner('Logging in with the newly registered customer account.', 'loading');
        await typeIntoField(form.querySelector('input[name="username"]'), customer.username, plan);
        await typeIntoField(form.querySelector('input[name="password"]'), customer.password, plan);
        state.customerLoginSubmitted = true;
        savePlan(plan);
        submitForm(form);
    }

    async function runHomepage(plan) {
        if (await navigateIfNeeded(plan, 'homepage')) {
            return;
        }
        showBanner('Walking through the homepage modules.', 'loading');
        showCart(plan, 'Demo Cart Overview');
        const highlights = [
            document.querySelector('header nav, nav.navbar, .navbar'),
            document.querySelector('input[type="search"], input[placeholder*="Search"], form input[type="text"]'),
            findTextMatch('h1, h2, h3, h4, section, a, button', ['featured', 'cakes']),
            findTextMatch('h1, h2, h3, h4, section, a, button', ['package']),
            document.querySelector('a[href*="/profile"]'),
            findTextMatch('h1, h2, h3, h4, section, a, button', ['about']),
            findTextMatch('h1, h2, h3, h4, section, a, button', ['contact'])
        ].filter(Boolean);
        for (const target of highlights) {
            target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
            highlightElement(target);
            await moveCursorTo(target);
            await wait(pace(plan, 720));
        }
        advancePlan(plan);
    }

    async function runCakeBrowse(plan) {
        if (await navigateIfNeeded(plan, 'cake_browse')) {
            return;
        }
        const showcase = plan.showcase_catalog || {};
        const card = Array.from(document.querySelectorAll('.card, .product-card, .cake-card, article')).find((element) => {
            return showcase.cake_name && (element.innerText || '').toLowerCase().includes(String(showcase.cake_name).toLowerCase());
        }) || document.querySelector('.card, .product-card, .cake-card, article');
        if (!card) {
            retryStep(plan, 'cake-browse-card', 'Waiting for the cakes catalog to finish rendering...');
            return;
        }
        resetAttempts(plan, 'cake-browse-card');
        showBanner('Browsing the live cakes catalog.', 'loading');
        highlightElement(card);
        await moveCursorTo(card);
        showCallout('This showcase cake is used as the live demo order.', card);
        await wait(pace(plan, 1200));
        advancePlan(plan);
    }
    async function runCakeCustomize(plan) {
        const state = runtime(plan);
        const orderTrackingPath = pathFromUrl(stepUrl(plan, 'order_tracking'));
        if (state.cakeSubmitted && window.location.pathname === orderTrackingPath) {
            plan.step_urls.cake_tracking = `${window.location.pathname}${window.location.search}`;
            savePlan(plan);
            showBanner('Cake order submitted successfully.', 'success');
            showCallout('The tracking page now shows the cake order number, payment status, and fulfillment status.');
            await wait(pace(plan, 1300));
            advancePlan(plan);
            return;
        }
        if (state.cakeSubmitted) {
            retryStep(plan, 'cake-submit-wait', 'Waiting for the cake order confirmation page...');
            return;
        }
        if (await navigateIfNeeded(plan, 'cake_customize')) {
            return;
        }
        const form = document.getElementById('cake-order-form');
        if (!form) {
            retryStep(plan, 'cake-order-form', 'Waiting for the cake customization form to finish loading...');
            return;
        }
        resetAttempts(plan, 'cake-order-form');
        showBanner('Completing the cake customization and payment flow.', 'loading');
        await chooseSelect(form.querySelector('select[name="theme"]'), ['birthday'], plan);
        await chooseInputByName('tier', ['1 tier', 'single'], plan, { index: 0 });
        await chooseInputByName('size', ['6 inches', '8 inches'], plan, { index: 0 });
        await chooseInputByName('shape', ['round'], plan, { index: 0 });
        await chooseInputByName('flavor', ['chocolate'], plan, { index: 0 });
        await chooseInputByName('frosting', ['buttercream'], plan, { index: 0 });
        await chooseInputByName('filling', ['chocolate', 'ganache'], plan, { index: 0 });
        await setFieldValue('input[name="color_palette"]', 'Blush pink and gold', plan);
        await setFieldValue('input[name="message_on_cake"]', 'Happy Demo Day Panel', plan);
        const addOn = form.querySelector('.addon-checkbox');
        if (addOn && !addOn.checked) {
            await clickElement(addOn, plan);
        }
        await setFieldValue('input[name="quantity"]', '1', plan);
        const deliveryDate = new Date();
        deliveryDate.setDate(deliveryDate.getDate() + 7);
        await setFieldValue('input[name="delivery_date"]', deliveryDate.toISOString().split('T')[0], plan);
        await setFieldValue('input[name="delivery_street_address"]', '123 Demo Street', plan);
        await setFieldValue('input[name="delivery_barangay"]', 'Poblacion 1', plan);
        await chooseSelect(form.querySelector('select[name="delivery_city"]'), ['lucena'], plan);
        await setFieldValue('input[name="delivery_landmark"]', 'Near City Hall', plan);
        await typeIntoField(form.querySelector('textarea[name="special_instructions"]'), 'Generated during the guided demo presentation.', plan);
        await setFieldValue('input[name="contact_name"]', 'Panel Demo', plan);
        await setFieldValue('input[name="contact_phone"]', '09171234567', plan);
        await setFieldValue('input[name="contact_email"]', buildCustomer(plan).email, plan);
        attachDemoFile(form.querySelector('input[name="design_reference"]'), 'cake-reference-demo.png');
        const gcashRadio = form.querySelector('input[name="payment_method"][value="gcash"]');
        if (gcashRadio && !gcashRadio.checked) {
            await clickElement(gcashRadio, plan);
        }
        const styleReviewButton = document.getElementById('cake-style-review-button');
        if (styleReviewButton) {
            await clickElement(styleReviewButton, plan);
        }
        const proofContinueButton = document.getElementById('continueToPaymentProof');
        if (proofContinueButton) {
            await clickElement(proofContinueButton, plan);
        }
        await setFieldValue('input[name="reference_number"]', `CAKE-${Date.now()}`, plan);
        attachDemoFile(form.querySelector('input[name="proof_image"]'), 'cake-payment-proof.png');
        const reviewContinueButton = document.getElementById('continueToOrderReview');
        if (reviewContinueButton) {
            await clickElement(reviewContinueButton, plan);
        }
        const reviewButton = document.getElementById('cake-review-button');
        if (reviewButton) {
            await clickElement(reviewButton, plan);
        }
        const confirmButton = document.getElementById('cake-confirm-button');
        state.cakeSubmitted = true;
        savePlan(plan);
        if (confirmButton) {
            await clickElement(confirmButton, plan);
            return;
        }
        submitForm(form);
    }

    async function setFirstQuantityCard(cardSelector, quantitySelector, plan) {
        const card = document.querySelector(cardSelector);
        if (!card) {
            return false;
        }
        const toggle = card.querySelector('[data-package-addon-toggle], [data-package-inclusion-toggle]') || card;
        await clickElement(toggle, plan);
        const quantityField = card.querySelector(quantitySelector);
        if (quantityField) {
            quantityField.value = '1';
            dispatchFieldEvents(quantityField);
            highlightElement(quantityField);
            await wait(pace(plan, 240));
        }
        return true;
    }

    async function runPackageBrowse(plan) {
        if (await navigateIfNeeded(plan, 'package_browse')) {
            return;
        }
        const showcase = plan.showcase_catalog || {};
        const card = Array.from(document.querySelectorAll('.package-catalog-card, .card, article')).find((element) => {
            return showcase.package_name && (element.innerText || '').toLowerCase().includes(String(showcase.package_name).toLowerCase());
        }) || document.querySelector('.package-catalog-card, .card, article');
        if (!card) {
            retryStep(plan, 'package-browse-card', 'Waiting for the package catalog to finish rendering...');
            return;
        }
        resetAttempts(plan, 'package-browse-card');
        showBanner('Browsing the live event packages catalog.', 'loading');
        highlightElement(card);
        await moveCursorTo(card);
        showCallout('This showcase package is used for the live package booking demo.', card);
        await wait(pace(plan, 1200));
        advancePlan(plan);
    }

    async function runPackageCustomize(plan) {
        const state = runtime(plan);
        const currentPath = window.location.pathname;
        const packageOrderPath = pathFromUrl(stepUrl(plan, 'package_order'));
        const packageCustomizePath = pathFromUrl(stepUrl(plan, 'package_cake_customize'));
        const packagePaymentPath = pathFromUrl(stepUrl(plan, 'package_payment'));
        if (currentPath === packagePaymentPath) {
            state.packageStepTwoSubmitted = true;
            savePlan(plan);
            showBanner('Package cake customization is complete. Checkout is ready.', 'success');
            await wait(pace(plan, 1200));
            advancePlan(plan);
            return;
        }
        const onPackageFlowPage = currentPath === packageOrderPath
            || currentPath === packageCustomizePath
            || currentPath === '/package-cake-customize/';
        if (!onPackageFlowPage && await navigateIfNeeded(plan, 'package_order')) {
            return;
        }
        if (currentPath === packageOrderPath) {
            const form = document.getElementById('package-step-one');
            if (!form) {
                retryStep(plan, 'package-step-one', 'Waiting for the package details form to finish loading...');
                return;
            }
            resetAttempts(plan, 'package-step-one');
            if (!state.packageStepOneSubmitted) {
                showBanner('Selecting the live package and optional add-ons.', 'loading');
                await setFirstQuantityCard('[data-package-inclusion-card]', '.package-inclusion-quantity', plan);
                await setFirstQuantityCard('[data-package-addon-card]', '.package-addon-quantity', plan);
                state.packageStepOneSubmitted = true;
                savePlan(plan);
            }
            const nextButton = form.querySelector('button[type="submit"]');
            if (nextButton) {
                await clickElement(nextButton, plan);
            } else {
                submitForm(form);
            }
            return;
        }
        if (currentPath === packageCustomizePath || currentPath === '/package-cake-customize/') {
            const form = document.getElementById('package-step-two');
            if (!form) {
                retryStep(plan, 'package-step-two', 'Waiting for the package cake customization form to finish loading...');
                return;
            }
            resetAttempts(plan, 'package-step-two');
            if (!state.packageStepTwoSubmitted) {
                showBanner('Customizing the package cake options.', 'loading');
                await chooseSelect(form.querySelector('select[name="theme"]'), ['birthday'], plan);
                await chooseInputByName('cake_size', ['10 inches', '8 inches'], plan, { index: 0 });
                await chooseInputByName('shape', ['round'], plan, { index: 0 });
                await chooseInputByName('flavor', ['chocolate'], plan, { index: 0 });
                await chooseInputByName('frosting', ['buttercream'], plan, { index: 0 });
                await chooseInputByName('filling', ['chocolate', 'ganache'], plan, { index: 0 });
                await setFieldValue('input[name="color_palette"]', 'White, blush, and gold', plan);
                await setFieldValue('input[name="message_on_cake"]', 'Celebration Demo', plan);
                const decoration = form.querySelector('.package-cake-decoration');
                if (decoration && !decoration.checked) {
                    await clickElement(decoration, plan);
                }
                await typeIntoField(form.querySelector('textarea[name="cake_instructions"]'), 'Keep the styling clean and presentation-ready.', plan);
                state.packageStepTwoSubmitted = true;
                savePlan(plan);
            }
            const nextButton = form.querySelector('button[type="submit"]');
            if (nextButton) {
                await clickElement(nextButton, plan);
            } else {
                submitForm(form);
            }
            return;
        }
        retryStep(plan, 'package-customize-route', 'Waiting for the package customization route to continue...');
    }

    async function runCartReview(plan) {
        if (await navigateIfNeeded(plan, 'cart_review')) {
            return;
        }
        showBanner('Reviewing the selected cake and package items.', 'loading');
        showCart(plan, 'Shopping Cart Review');
        const summary = findTextMatch('.card, .checkout-summary-card, h5, h6, div', ['summary', 'grand total', 'order number']);
        if (summary) {
            summary.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
            highlightElement(summary);
            await moveCursorTo(summary);
        }
        await wait(pace(plan, 1300));
        advancePlan(plan);
    }

    async function runCheckout(plan) {
        const state = runtime(plan);
        if (state.checkoutFilled) {
            advancePlan(plan);
            return;
        }
        if (await navigateIfNeeded(plan, 'checkout')) {
            return;
        }
        const form = document.getElementById('package-step-three');
        if (!form) {
            retryStep(plan, 'package-step-three', 'Waiting for the package checkout form to finish loading...');
            return;
        }
        resetAttempts(plan, 'package-step-three');
        const eventDate = new Date();
        eventDate.setDate(eventDate.getDate() + 14);
        showBanner('Filling the event schedule and checkout details.', 'loading');
        await setFieldValue('input[name="event_date"]', eventDate.toISOString().split('T')[0], plan);
        await setFieldValue('input[name="event_time"]', '14:00', plan);
        await typeIntoField(form.querySelector('textarea[name="venue"]'), 'Hanilies Demo Hall, Lucena City', plan);
        await setFieldValue('input[name="contact_name"]', 'Panel Demo', plan);
        await setFieldValue('input[name="contact_phone"]', '09171234567', plan);
        await setFieldValue('input[name="contact_email"]', buildCustomer(plan).email, plan);
        attachDemoFile(form.querySelector('input[name="design_reference"]'), 'package-setup-reference.png');
        const gcashRadio = form.querySelector('input[name="payment_method"][value="gcash"]');
        if (gcashRadio && !gcashRadio.checked) {
            await clickElement(gcashRadio, plan);
        }
        state.checkoutFilled = true;
        savePlan(plan);
        await wait(pace(plan, 900));
        advancePlan(plan);
    }

    async function runPayment(plan) {
        const state = runtime(plan);
        const orderTrackingPath = pathFromUrl(stepUrl(plan, 'order_tracking'));
        if (state.packageSubmitted && window.location.pathname === orderTrackingPath) {
            plan.step_urls.package_tracking = `${window.location.pathname}${window.location.search}`;
            savePlan(plan);
            showBanner('Package payment proof submitted successfully.', 'success');
            await wait(pace(plan, 1200));
            advancePlan(plan);
            return;
        }
        if (state.packageSubmitted) {
            retryStep(plan, 'package-submit-wait', 'Waiting for the package order confirmation page...');
            return;
        }
        if (await navigateIfNeeded(plan, 'payment')) {
            return;
        }
        const form = document.getElementById('package-step-three');
        if (!form) {
            retryStep(plan, 'package-payment-form', 'Waiting for the package payment form to finish loading...');
            return;
        }
        resetAttempts(plan, 'package-payment-form');
        showBanner('Showing the payment QR code and manual proof upload.', 'loading');
        const qrImage = document.getElementById('package-gcash-qr-image');
        if (qrImage) {
            qrImage.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
            highlightElement(qrImage);
            await moveCursorTo(qrImage);
            await wait(pace(plan, 1100));
        }
        const proofStepButton = document.getElementById('packageContinueToPaymentProof');
        if (proofStepButton) {
            await clickElement(proofStepButton, plan);
        }
        await setFieldValue('input[name="reference_number"]', `PACKAGE-${Date.now()}`, plan);
        attachDemoFile(form.querySelector('input[name="proof_image"]'), 'package-payment-proof.png');
        const orderReviewButton = document.getElementById('packageContinueToOrderReview');
        if (orderReviewButton) {
            await clickElement(orderReviewButton, plan);
        }
        const reviewButton = document.getElementById('package-review-button');
        if (reviewButton) {
            await clickElement(reviewButton, plan);
        }
        const confirmButton = document.getElementById('package-confirm-button');
        state.packageSubmitted = true;
        savePlan(plan);
        if (confirmButton) {
            await clickElement(confirmButton, plan);
            return;
        }
        submitForm(form);
    }

    async function runCustomerOrders(plan) {
        const state = runtime(plan);
        const orderTrackingPath = pathFromUrl(stepUrl(plan, 'order_tracking'));
        const ordersUrl = stepUrl(plan, 'customer_orders');
        if (window.location.pathname === orderTrackingPath) {
            showBanner('Displaying the live customer order confirmation details.', 'success');
            const details = [
                findTextMatch('h1, h2, h3, h4, div, span', ['order number']),
                findTextMatch('h1, h2, h3, h4, div, span', ['total amount', 'grand total']),
                findTextMatch('h1, h2, h3, h4, div, span', ['payment status']),
                findTextMatch('h1, h2, h3, h4, div, span', ['order status'])
            ].filter(Boolean);
            for (const item of details) {
                highlightElement(item);
                await moveCursorTo(item);
                await wait(pace(plan, 650));
            }
            state.ordersViewed = true;
            savePlan(plan);
            advancePlan(plan);
            return;
        }
        if (!matchesTarget(ordersUrl)) {
            window.location.assign(ordersUrl);
            return;
        }
        showBanner('Opening My Orders and tracking links.', 'loading');
        const firstOrderLink = document.querySelector('.order-history-link, a[href*="/order-tracking/"]');
        if (firstOrderLink && !state.ordersLinkOpened) {
            state.ordersLinkOpened = true;
            savePlan(plan);
            await clickElement(firstOrderLink, plan);
            return;
        }
        const orderCard = document.querySelector('.order-history-link, .order-card, .list-group-item, .card');
        if (orderCard) {
            highlightElement(orderCard);
            await moveCursorTo(orderCard);
        }
        await wait(pace(plan, 900));
        advancePlan(plan);
    }

    async function runAdminLogin(plan) {
        const state = runtime(plan);
        const loginPath = pathFromUrl(stepUrl(plan, 'admin_login'));
        const dashboardPath = pathFromUrl(stepUrl(plan, 'admin_dashboard'));
        const credentials = plan.admin_credentials || {};
        if (state.adminLoginSubmitted && window.location.pathname === dashboardPath) {
            showBanner('Administrator login successful.', 'success');
            await wait(pace(plan, 1200));
            advancePlan(plan);
            return;
        }
        if (!state.adminLogoutStarted && window.location.pathname !== loginPath) {
            state.adminLogoutStarted = true;
            savePlan(plan);
            window.location.assign(stepUrl(plan, 'logout'));
            return;
        }
        if (await navigateIfNeeded(plan, 'admin_login')) {
            return;
        }
        const form = document.querySelector('form[action*="/login/"]');
        if (!form) {
            retryStep(plan, 'admin-login-form', 'Waiting for the administrator login form to finish loading...');
            return;
        }
        resetAttempts(plan, 'admin-login-form');
        showBanner('Signing in as the demonstration administrator.', 'loading');
        await typeIntoField(form.querySelector('input[name="username"]'), credentials.username || 'paneladmin', plan);
        await typeIntoField(form.querySelector('input[name="password"]'), credentials.password || 'PanelAdmin123!', plan);
        state.adminLoginSubmitted = true;
        savePlan(plan);
        submitForm(form);
    }

    async function runAdminDashboard(plan) {
        if (await navigateIfNeeded(plan, 'admin_dashboard')) {
            return;
        }
        showBanner('Highlighting the dashboard statistics and recent operations.', 'loading');
        const cards = Array.from(document.querySelectorAll('.stat-card, .quick-action-card, .dashboard-data-grid .module-card')).slice(0, 7);
        for (const card of cards) {
            card.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
            highlightElement(card);
            await moveCursorTo(card);
            await wait(pace(plan, 560));
        }
        advancePlan(plan);
    }

    function orderRows(preferredText) {
        const rows = Array.from(document.querySelectorAll('table tbody tr'));
        if (!preferredText) {
            return rows;
        }
        const matchingRow = rows.find((row) => (row.innerText || '').toLowerCase().includes(String(preferredText).toLowerCase()));
        return matchingRow ? [matchingRow].concat(rows.filter((row) => row !== matchingRow)) : rows;
    }

    function selectNextStatus(selectField) {
        if (!selectField) {
            return false;
        }
        const options = Array.from(selectField.options);
        const currentValue = selectField.dataset.currentValue || selectField.value;
        const preferred = options.find((option) => option.value && option.value !== currentValue && option.value !== 'delete');
        const fallback = options.find((option) => option.value && option.value !== currentValue);
        const target = preferred || fallback;
        if (!target) {
            return false;
        }
        selectField.value = target.value;
        dispatchFieldEvents(selectField);
        return true;
    }

    async function runOrderManagement(plan, config) {
        const state = runtime(plan);
        const phaseKey = `${config.stateKey}Phase`;
        const phase = state[phaseKey] || 'preview';
        const listUrl = stepUrl(plan, config.stepKey);
        const listPath = pathFromUrl(listUrl);
        if (window.location.pathname !== listPath && phase === 'preview') {
            showBanner(config.previewMessage, 'loading');
            const previewCard = document.querySelector('.module-card, .card, .summary-block, .table-responsive');
            if (previewCard) {
                highlightElement(previewCard);
                await moveCursorTo(previewCard);
                showCallout(config.detailsMessage, previewCard);
            }
            state[phaseKey] = 'update';
            savePlan(plan);
            await wait(pace(plan, 1300));
            const backLink = document.querySelector('.btn-preview-back');
            if (backLink && backLink.href) {
                window.location.assign(backLink.href);
                return;
            }
            if (listUrl) {
                window.location.assign(listUrl);
                return;
            }
            window.history.back();
            return;
        }
        if (window.location.pathname !== listPath && phase === 'update' && listUrl) {
            window.location.assign(listUrl);
            return;
        }
        if (await navigateIfNeeded(plan, config.stepKey)) {
            return;
        }
        const row = orderRows(buildCustomer(plan).username)[0] || document.querySelector('table tbody tr');
        if (!row) {
            retryStep(plan, `${config.stateKey}-row`, config.waitMessage);
            return;
        }
        resetAttempts(plan, `${config.stateKey}-row`);
        if (phase === 'preview') {
            const previewLink = row.querySelector('.btn-preview, a[href*="/view/"]');
            if (!previewLink) {
                state[phaseKey] = 'update';
                savePlan(plan);
            } else {
                await clickElement(previewLink, plan);
                return;
            }
        }
        if (state[phaseKey] === 'update') {
            showBanner(config.updateMessage, 'loading');
            const selectField = row.querySelector('select[name="action"]');
            if (selectNextStatus(selectField)) {
                const applyButton = row.querySelector('button[type="submit"]');
                state[phaseKey] = 'done';
                savePlan(plan);
                if (applyButton) {
                    await clickElement(applyButton, plan);
                    return;
                }
                submitForm(row.querySelector('form'));
                return;
            }
            state[phaseKey] = 'done';
            savePlan(plan);
        }
        if (state[phaseKey] === 'done') {
            showBanner('Admin queue review complete. Moving to the next admin module.', 'success');
            await wait(pace(plan, 700));
        }
        advancePlan(plan);
    }
    async function runAdminPayments(plan) {
        const state = runtime(plan);
        const phase = state.adminPaymentsPhase || 'proof';
        if (await navigateIfNeeded(plan, 'admin_payments')) {
            return;
        }
        if (phase === 'proof') {
            const proofButton = document.querySelector('.btn-view');
            if (proofButton) {
                showBanner('Opening the uploaded payment proof.', 'loading');
                state.adminPaymentsPhase = 'approve';
                savePlan(plan);
                await clickElement(proofButton, plan);
                await wait(pace(plan, 900));
                const proofImage = document.getElementById('proofImage');
                if (proofImage) {
                    highlightElement(proofImage);
                    await moveCursorTo(proofImage);
                    showCallout('The proof image and reference number are reviewed here before approval.', proofImage);
                    await wait(pace(plan, 900));
                }
                if (typeof window.closeModal === 'function') {
                    window.closeModal();
                }
                scheduleRun(pace(plan, 420));
                return;
            }
            state.adminPaymentsPhase = 'approve';
            savePlan(plan);
        }
        if (state.adminPaymentsPhase === 'approve') {
            const approveButton = document.querySelector('button[name="action"][value="approve"]');
            if (approveButton) {
                showBanner('Approving the pending payment submission.', 'loading');
                state.adminPaymentsPhase = 'done';
                savePlan(plan);
                await clickElement(approveButton, plan);
                return;
            }
            state.adminPaymentsPhase = 'done';
            savePlan(plan);
        }
        advancePlan(plan);
    }

    async function fillAdminCakeForm(plan, form, name) {
        await typeIntoField(form.querySelector('input[name="name"]'), name, plan);
        await chooseSelect(form.querySelector('select[name="category"]'), ['birthday', 'custom'], plan);
        await typeIntoField(form.querySelector('textarea[name="description"]'), 'Created during the guided admin demo flow.', plan);
        await typeIntoField(form.querySelector('input[name="price"]'), '1899', plan);
        await typeIntoField(form.querySelector('input[name="stock"]'), '8', plan);
        const active = form.querySelector('input[name="is_active"]');
        if (active && !active.checked) {
            await clickElement(active, plan);
        }
    }

    async function fillAdminPackageForm(plan, form, name) {
        await typeIntoField(form.querySelector('input[name="name"]'), name, plan);
        await chooseSelect(form.querySelector('select[name="package_type"]'), ['kids', 'birthday'], plan);
        await typeIntoField(form.querySelector('textarea[name="description"]'), 'Created during the guided admin package management demo.', plan);
        await typeIntoField(form.querySelector('input[name="base_price"]'), '8800', plan);
        await chooseSelect(form.querySelector('select[name="status"]'), ['active'], plan);
        const addInclusionButton = form.querySelector('.package-inclusion-add');
        let inclusionRow = form.querySelector('.package-inclusion-row');
        if (!inclusionRow && addInclusionButton) {
            await clickElement(addInclusionButton, plan);
            inclusionRow = form.querySelector('.package-inclusion-row');
        }
        if (inclusionRow) {
            await typeIntoField(inclusionRow.querySelector('[data-field="label"]'), 'Stage decor setup', plan);
            await typeIntoField(inclusionRow.querySelector('[data-field="quantity"]'), '1', plan);
            await typeIntoField(inclusionRow.querySelector('[data-field="price"]'), '0.00', plan);
        }
    }

    async function runAdminCakes(plan) {
        const state = runtime(plan);
        state.demoCakeName = state.demoCakeName || `Demo Showcase Cake ${Date.now().toString().slice(-6)}`;
        const phase = state.adminCakePhase || 'open-add';
        if (await navigateIfNeeded(plan, 'admin_cakes')) {
            return;
        }
        if (window.location.pathname.includes('/admin-panel/cakes/add/')) {
            const form = document.querySelector('form');
            if (!form) {
                retryStep(plan, 'admin-cake-add-form', 'Waiting for the add cake form to finish loading...');
                return;
            }
            showBanner('Adding a cake product from the admin panel.', 'loading');
            await fillAdminCakeForm(plan, form, state.demoCakeName);
            state.adminCakePhase = 'open-edit';
            savePlan(plan);
            submitForm(form);
            return;
        }
        if (window.location.pathname.includes('/admin-panel/cakes/edit/')) {
            const form = document.querySelector('form');
            if (!form) {
                retryStep(plan, 'admin-cake-edit-form', 'Waiting for the edit cake form to finish loading...');
                return;
            }
            showBanner('Editing the created cake product.', 'loading');
            await typeIntoField(form.querySelector('textarea[name="description"]'), 'Updated during the guided admin cake edit demonstration.', plan);
            await typeIntoField(form.querySelector('input[name="price"]'), '1999', plan);
            state.adminCakePhase = 'archive';
            savePlan(plan);
            submitForm(form);
            return;
        }
        const row = Array.from(document.querySelectorAll('table tbody tr')).find((candidate) => {
            return (candidate.innerText || '').toLowerCase().includes(state.demoCakeName.toLowerCase());
        });
        if (phase === 'open-add') {
            const addLink = findTextMatch('a, button', ['add new cake']);
            if (addLink) {
                state.adminCakePhase = 'adding';
                savePlan(plan);
                await clickElement(addLink, plan);
                return;
            }
        }
        if ((state.adminCakePhase === 'open-edit' || state.adminCakePhase === 'adding') && row) {
            const editLink = row.querySelector('a[href*="/edit/"]');
            if (editLink) {
                state.adminCakePhase = 'editing';
                savePlan(plan);
                await clickElement(editLink, plan);
                return;
            }
        }
        if (state.adminCakePhase === 'archive' && row) {
            const archiveButton = Array.from(row.querySelectorAll('button[type="submit"]')).find((button) => {
                return (button.innerText || '').toLowerCase().includes('archive') || (button.innerText || '').toLowerCase().includes('restore');
            }) || row.querySelector('button[type="submit"]');
            if (archiveButton) {
                showBanner('Archiving the demo cake product.', 'loading');
                state.adminCakePhase = 'done';
                savePlan(plan);
                await clickElement(archiveButton, plan);
                return;
            }
        }
        if (state.adminCakePhase === 'done') {
            advancePlan(plan);
            return;
        }
        const cakeListAttempts = attempts(plan)['admin-cake-list'] || 0;
        if (cakeListAttempts >= 2) {
            showBanner('Cake management page reviewed. Moving to the next admin module.', 'success');
            state.adminCakePhase = 'done';
            savePlan(plan);
            await wait(pace(plan, 700));
            advancePlan(plan);
            return;
        }
        retryStep(plan, 'admin-cake-list', 'Waiting for the cake management list to finish refreshing...');
    }

    async function runAdminPackages(plan) {
        const state = runtime(plan);
        state.demoPackageName = state.demoPackageName || `Demo Showcase Package ${Date.now().toString().slice(-6)}`;
        const phase = state.adminPackagePhase || 'open-add';
        if (await navigateIfNeeded(plan, 'admin_packages')) {
            return;
        }
        if (window.location.pathname.includes('/admin-panel/packages/add/')) {
            const form = document.querySelector('form');
            if (!form) {
                retryStep(plan, 'admin-package-add-form', 'Waiting for the add package form to finish loading...');
                return;
            }
            showBanner('Adding a package product from the admin panel.', 'loading');
            await fillAdminPackageForm(plan, form, state.demoPackageName);
            state.adminPackagePhase = 'open-edit';
            savePlan(plan);
            submitForm(form);
            return;
        }
        if (window.location.pathname.includes('/admin-panel/packages/edit/')) {
            const form = document.querySelector('form');
            if (!form) {
                retryStep(plan, 'admin-package-edit-form', 'Waiting for the edit package form to finish loading...');
                return;
            }
            showBanner('Editing the created package product.', 'loading');
            await typeIntoField(form.querySelector('textarea[name="description"]'), 'Updated during the guided admin package edit demonstration.', plan);
            await typeIntoField(form.querySelector('input[name="base_price"]'), '9400', plan);
            state.adminPackagePhase = 'archive';
            savePlan(plan);
            submitForm(form);
            return;
        }
        const row = Array.from(document.querySelectorAll('table tbody tr')).find((candidate) => {
            return (candidate.innerText || '').toLowerCase().includes(state.demoPackageName.toLowerCase());
        });
        if (phase === 'open-add') {
            const addLink = findTextMatch('a, button', ['add new package']);
            if (addLink) {
                state.adminPackagePhase = 'adding';
                savePlan(plan);
                await clickElement(addLink, plan);
                return;
            }
        }
        if ((state.adminPackagePhase === 'open-edit' || state.adminPackagePhase === 'adding') && row) {
            const editLink = row.querySelector('a[href*="/edit/"]');
            if (editLink) {
                state.adminPackagePhase = 'editing';
                savePlan(plan);
                await clickElement(editLink, plan);
                return;
            }
        }
        if (state.adminPackagePhase === 'archive' && row) {
            const archiveButton = Array.from(row.querySelectorAll('button[type="submit"]')).find((button) => {
                return (button.innerText || '').toLowerCase().includes('archive') || (button.innerText || '').toLowerCase().includes('restore');
            }) || row.querySelector('button[type="submit"]');
            if (archiveButton) {
                showBanner('Archiving the demo package product.', 'loading');
                state.adminPackagePhase = 'done';
                savePlan(plan);
                await clickElement(archiveButton, plan);
                return;
            }
        }
        if (state.adminPackagePhase === 'done') {
            advancePlan(plan);
            return;
        }
        const packageListAttempts = attempts(plan)['admin-package-list'] || 0;
        if (packageListAttempts >= 2) {
            showBanner('Package management page reviewed. Moving to the next admin module.', 'success');
            state.adminPackagePhase = 'done';
            savePlan(plan);
            await wait(pace(plan, 700));
            advancePlan(plan);
            return;
        }
        retryStep(plan, 'admin-package-list', 'Waiting for the package management list to finish refreshing...');
    }
    async function runAdminUsers(plan) {
        const state = runtime(plan);
        const suffix = Date.now().toString().slice(-6);
        state.demoAdminUser = state.demoAdminUser || {
            first_name: 'Demo',
            last_name: 'Staff',
            email: `staff.demo.${suffix}@example.com`,
            username: `staffdemo${suffix}`,
            phone: '09175554444',
            address: 'Hanilies Admin Office, Demo Street',
            password: 'StaffDemo123!'
        };
        if (await navigateIfNeeded(plan, 'admin_users')) {
            return;
        }
        if (window.location.pathname.includes('/admin-panel/users/add/')) {
            const form = document.querySelector('form');
            if (!form) {
                retryStep(plan, 'admin-user-add-form', 'Waiting for the create user form to finish loading...');
                return;
            }
            showBanner('Creating a demo staff account from the admin panel.', 'loading');
            const user = state.demoAdminUser;
            await typeIntoField(form.querySelector('input[name="first_name"]'), user.first_name, plan);
            await typeIntoField(form.querySelector('input[name="last_name"]'), user.last_name, plan);
            await typeIntoField(form.querySelector('input[name="email"]'), user.email, plan);
            await typeIntoField(form.querySelector('input[name="username"]'), user.username, plan);
            await typeIntoField(form.querySelector('input[name="phone"]'), user.phone, plan);
            await typeIntoField(form.querySelector('textarea[name="address"]'), user.address, plan);
            await chooseSelect(form.querySelector('select[name="role"]'), ['cashier', 'staff', 'admin'], plan);
            await typeIntoField(form.querySelector('input[name="password"]'), user.password, plan);
            await typeIntoField(form.querySelector('input[name="confirm_password"]'), user.password, plan);
            state.adminUserPhase = 'open-edit';
            savePlan(plan);
            submitForm(form);
            return;
        }
        if (window.location.pathname.includes('/admin-panel/users/edit/')) {
            const form = document.querySelector('form');
            if (!form) {
                retryStep(plan, 'admin-user-edit-form', 'Waiting for the edit user form to finish loading...');
                return;
            }
            showBanner('Editing the created staff account.', 'loading');
            await typeIntoField(form.querySelector('input[name="phone"]'), '09176667777', plan);
            await typeIntoField(form.querySelector('textarea[name="address"]'), 'Updated during the guided admin user edit demonstration.', plan);
            state.adminUserPhase = 'open-role';
            savePlan(plan);
            submitForm(form);
            return;
        }
        if (window.location.pathname.includes('/admin-panel/users/role/')) {
            const form = document.querySelector('form');
            if (!form) {
                retryStep(plan, 'admin-user-role-form', 'Waiting for the role assignment form to finish loading...');
                return;
            }
            showBanner('Assigning a staff role to the created user.', 'loading');
            await chooseSelect(form.querySelector('select[name="role"]'), ['cashier', 'manager', 'admin'], plan);
            state.adminUserPhase = 'archive';
            savePlan(plan);
            submitForm(form);
            return;
        }
        const user = state.demoAdminUser;
        const row = Array.from(document.querySelectorAll('table tbody tr')).find((candidate) => {
            return (candidate.innerText || '').toLowerCase().includes(user.username.toLowerCase());
        });
        if (!state.adminUserPhase) {
            state.adminUserPhase = 'open-add';
            savePlan(plan);
        }
        if (state.adminUserPhase === 'open-add') {
            const createUserLink = findTextMatch('a, button', ['create user']);
            if (createUserLink) {
                state.adminUserPhase = 'adding';
                savePlan(plan);
                await clickElement(createUserLink, plan);
                return;
            }
        }
        if ((state.adminUserPhase === 'open-edit' || state.adminUserPhase === 'adding') && row) {
            const editLink = row.querySelector('a[href*="/edit/"]');
            if (editLink) {
                state.adminUserPhase = 'editing';
                savePlan(plan);
                await clickElement(editLink, plan);
                return;
            }
        }
        if (state.adminUserPhase === 'open-role' && row) {
            const roleLink = Array.from(row.querySelectorAll('a')).find((link) => {
                return (link.innerText || '').toLowerCase().includes('change role');
            });
            if (roleLink) {
                state.adminUserPhase = 'role';
                savePlan(plan);
                await clickElement(roleLink, plan);
                return;
            }
        }
        if (state.adminUserPhase === 'archive' && row) {
            const archiveButton = Array.from(row.querySelectorAll('button[type="submit"]')).find((button) => {
                return (button.innerText || '').toLowerCase().includes('archive') || (button.innerText || '').toLowerCase().includes('restore');
            }) || row.querySelector('button[type="submit"]');
            if (archiveButton) {
                showBanner('Archiving the created demo staff account.', 'loading');
                state.adminUserPhase = 'done';
                savePlan(plan);
                await clickElement(archiveButton, plan);
                return;
            }
        }
        if (state.adminUserPhase === 'done') {
            advancePlan(plan);
            return;
        }
        const userListAttempts = attempts(plan)['admin-user-list'] || 0;
        if (userListAttempts >= 2) {
            showBanner('User management page reviewed. Moving to the next admin module.', 'success');
            state.adminUserPhase = 'done';
            savePlan(plan);
            await wait(pace(plan, 700));
            advancePlan(plan);
            return;
        }
        retryStep(plan, 'admin-user-list', 'Waiting for the user management list to finish refreshing...');
    }

    async function runAuditTrail(plan) {
        const state = runtime(plan);
        const currentTab = window.location.search.toLowerCase().includes('tab=export');
        if (await navigateIfNeeded(plan, 'audit_trail')) {
            return;
        }
        const filterForm = document.querySelector('form.audit-ui-filter-card');
        if (!state.auditFilterSubmitted && filterForm) {
            showBanner('Filtering the activity logs for the presentation highlights.', 'loading');
            const searchInput = filterForm.querySelector('input[name="q"]');
            if (searchInput) {
                await typeIntoField(searchInput, 'payment', plan);
            }
            state.auditFilterSubmitted = true;
            savePlan(plan);
            submitForm(filterForm);
            return;
        }
        const exportTab = findTextMatch('.audit-ui-tab', ['export logs']);
        if (!state.auditExportOpened && exportTab && !currentTab) {
            showBanner('Opening the export tools for the audit trail.', 'loading');
            state.auditExportOpened = true;
            savePlan(plan);
            await clickElement(exportTab, plan);
            return;
        }
        const exportCards = Array.from(document.querySelectorAll('.audit-ui-export-card'));
        if (exportCards.length) {
            showBanner('Showing the available audit log export formats.', 'success');
            for (const card of exportCards.slice(0, 4)) {
                highlightElement(card);
                await moveCursorTo(card);
                await wait(pace(plan, 520));
            }
        } else if (filterForm) {
            highlightElement(filterForm);
            await moveCursorTo(filterForm);
            await wait(pace(plan, 900));
        }
        advancePlan(plan);
    }

    async function runAdminLogout(plan) {
        const state = runtime(plan);
        const loginUrl = stepUrl(plan, 'admin_login');
        if (state.adminLogoutStarted && matchesTarget(loginUrl)) {
            showBanner('Demo completed successfully.', 'success');
            await wait(pace(plan, 900));
            finishDemo('Demo completed successfully.');
            return;
        }
        if (!state.adminLogoutStarted) {
            state.adminLogoutStarted = true;
            savePlan(plan);
            window.location.assign(stepUrl(plan, 'admin_logout'));
            return;
        }
        if (!matchesTarget(loginUrl)) {
            window.location.assign(loginUrl);
            return;
        }
        finishDemo('Demo completed successfully.');
    }

    async function runStep(plan) {
        const step = currentStep(plan);
        if (!step) {
            await finishDemo('Demo completed successfully.');
            return;
        }
        setStatus(stepMessages[step] || 'Running the presentation walkthrough...', 'loading');
        setControlState(true);
        showBanner(stepMessages[step] || 'Running the presentation walkthrough...', 'loading');
        const handlers = {
            intro: runIntro,
            register: runRegister,
            customer_login: runCustomerLogin,
            homepage: runHomepage,
            cake_browse: runCakeBrowse,
            cake_customize: runCakeCustomize,
            package_browse: runPackageBrowse,
            package_customize: runPackageCustomize,
            cart_review: runCartReview,
            checkout: runCheckout,
            payment: runPayment,
            customer_orders: runCustomerOrders,
            admin_login: runAdminLogin,
            admin_dashboard: runAdminDashboard,
            admin_cake_orders: (activePlan) => runOrderManagement(activePlan, {
                stepKey: 'admin_cake_orders',
                stateKey: 'adminCakeOrders',
                previewMessage: 'Opening the submitted cake order summary.',
                detailsMessage: 'The admin summary shows the customer order, customization choices, payment details, and tracking status.',
                updateMessage: 'Updating the cake order status from the list.',
                waitMessage: 'Waiting for the cake orders table to finish loading...'
            }),
            admin_package_orders: (activePlan) => runOrderManagement(activePlan, {
                stepKey: 'admin_package_orders',
                stateKey: 'adminPackageOrders',
                previewMessage: 'Opening the submitted package order summary.',
                detailsMessage: 'The admin summary shows the event schedule, package selections, payment details, and fulfillment status.',
                updateMessage: 'Updating the package order status from the list.',
                waitMessage: 'Waiting for the package orders table to finish loading...'
            }),
            admin_payments: runAdminPayments,
            admin_cakes: runAdminCakes,
            admin_packages: runAdminPackages,
            admin_users: runAdminUsers,
            audit_trail: runAuditTrail,
            admin_logout: runAdminLogout
        };
        const handler = handlers[step];
        if (!handler) {
            advancePlan(plan);
            return;
        }
        await handler(plan);
    }

    async function maybeRunBrowserDemo() {
        const plan = restoreDemoGuards();
        if (!plan || plan.mode !== 'browser') {
            cleanupVisuals();
            return;
        }
        if (isExecuting) {
            return;
        }
        isExecuting = true;
        try {
            await runStep(plan);
        } catch (error) {
            console.error('Demo bot error:', error);
            setStatus(error.message || 'The demo bot encountered an unexpected error.', 'error');
            clearPlan();
            setControlState(false);
        } finally {
            isExecuting = false;
        }
    }

    async function startDemo(scenario, customSteps) {
        if (isLaunching || isStopping || lastRunningState) {
            return;
        }
        if (scenario === 'custom' && !customSteps.length) {
            setStatus('Choose at least one presentation step before starting the selected-step demo.', 'error');
            return;
        }
        isLaunching = true;
        setControlState(false);
        const selectedFlowLabel = scenario === 'custom' ? 'selected demo' : (scenarioLabels[scenario] || scenario);
        setStatus(`Starting the ${selectedFlowLabel} at ${selectedPaceLabel()} pace...`, 'loading');
        try {
            const response = await fetch(startEndpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfTokenInput ? csrfTokenInput.value : '',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(payloadForScenario(scenario, customSteps))
            });
            const data = await readJsonResponse(response);
            if (!response.ok || !data.ok) {
                throw new Error(data.error || 'Unable to start the demo bot.');
            }
            if (!data.browser_demo) {
                throw new Error('The server did not return a browser demo plan.');
            }
            clearPlan();
            const plan = {
                ...data.browser_demo,
                mode: 'browser',
                currentIndex: 0,
                delay: parseFloatOrDefault(delaySelect && delaySelect.value, data.browser_demo.delay || 1.15)
            };
            savePlan(plan);
            setStatus(data.message, 'success');
            setControlState(true);
            window.location.assign(data.browser_demo.launch_url);
        } catch (error) {
            setStatus(error.message || 'Unable to start the demo bot.', 'error');
            clearPlan();
            setControlState(false);
        } finally {
            isLaunching = false;
        }
    }

    async function stopDemo() {
        if (isStopping || isLaunching || !lastRunningState) {
            clearPlan();
            setControlState(false);
            return;
        }
        isStopping = true;
        setStatus('Stopping the active demo...', 'loading');
        try {
            const response = await fetch(stopEndpoint, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfTokenInput ? csrfTokenInput.value : '',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            const data = await readJsonResponse(response);
            if (!response.ok || !data.ok) {
                throw new Error(data.error || 'Unable to stop the demo bot.');
            }
            clearPlan();
            setStatus(data.message, 'success');
            setControlState(false);
        } catch (error) {
            setStatus(error.message || 'Unable to stop the demo bot.', 'error');
        } finally {
            isStopping = false;
        }
    }

    function describeActiveDemo(activeDemo) {
        if (!activeDemo) {
            return 'A demo is currently running.';
        }
        if (activeDemo.scenario === 'custom') {
            return 'Running a selected-step presentation flow.';
        }
        return `Running the ${scenarioLabels[activeDemo.scenario] || activeDemo.scenario}.`;
    }

    async function refreshStatus() {
        try {
            const response = await fetch(statusEndpoint, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const data = await readJsonResponse(response);
            if (!data.ok) {
                return;
            }
            if (data.running) {
                setStatus(describeActiveDemo(data.active_demo), 'loading');
                setControlState(true);
                return;
            }
            if (!data.running && !loadPlan()) {
                if (!isLaunching && !isStopping) {
                    setStatus('Ready. Start the full guided demo or run a selected presentation flow.', 'idle');
                }
                setControlState(false);
            }
        } catch (error) {
            if (!isLaunching && !isStopping) {
                setStatus('Unable to refresh the demo status right now.', 'error');
            }
        }
    }

    startButtons.forEach((button) => {
        button.addEventListener('click', () => {
            startDemo(button.dataset.scenario, []);
        });
    });

    if (customButton) {
        customButton.addEventListener('click', () => {
            startDemo('custom', selectedScriptSteps());
        });
    }

    if (stopButton) {
        stopButton.addEventListener('click', () => {
            stopDemo();
        });
    }

    setControlState(false);
    restoreDemoGuards();
    refreshStatus();
    maybeRunBrowserDemo();
    refreshTimer = window.setInterval(refreshStatus, 4000);

    window.addEventListener('beforeunload', () => {
        if (refreshTimer) {
            window.clearInterval(refreshTimer);
        }
    });
})();

















