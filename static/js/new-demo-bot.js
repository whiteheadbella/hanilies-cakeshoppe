(function () {
    'use strict';

    var STORAGE_KEY = 'hanilies.presentationDemo.state';
    var SELECTED_KEY = 'hanilies.presentationDemo.selectedSteps';
    var OLD_STORAGE_KEYS = ['hanilies.newDemoBot.state', 'haniliesDemoBotV2'];
    var MAX_RUN_TIME = 15 * 60 * 1000;

    var config = null;
    var root = null;
    var highlightNode = null;
    var calloutNode = null;
    var runningTimer = null;
    var isRunning = false;

    function storage(kind) {
        return kind === 'local' ? window.localStorage : window.sessionStorage;
    }

    function readJson(key, fallback, kind) {
        try {
            var value = storage(kind).getItem(key);
            return value ? JSON.parse(value) : fallback;
        } catch (error) {
            return fallback;
        }
    }

    function writeJson(key, value, kind) {
        try {
            storage(kind).setItem(key, JSON.stringify(value));
        } catch (error) {
            return false;
        }
        return true;
    }

    function removeStorageKey(key, kind) {
        try {
            storage(kind).removeItem(key);
        } catch (error) {
            return false;
        }
        return true;
    }

    function getState() {
        return readJson(STORAGE_KEY, null, 'session');
    }

    function setState(state) {
        writeJson(STORAGE_KEY, state, 'session');
    }

    function clearState() {
        removeStorageKey(STORAGE_KEY, 'session');
        removeStorageKey(STORAGE_KEY, 'local');
    }

    function cleanupOldDemoState() {
        OLD_STORAGE_KEYS.forEach(function (key) {
            removeStorageKey(key, 'session');
            removeStorageKey(key, 'local');
        });
    }

    function currentPath() {
        return window.location.pathname + window.location.search;
    }

    function pathFromUrl(url) {
        var parser = document.createElement('a');
        parser.href = url;
        return parser.pathname + parser.search;
    }

    function samePath(url) {
        return pathFromUrl(url) === currentPath();
    }

    function panel() {
        return root.querySelector('[data-new-tour-shell]');
    }

    function setPanelOpen(isOpen) {
        var shell = panel();
        var toggle = root.querySelector('[data-demo-toggle]');
        if (!shell || !toggle) {
            return;
        }
        shell.hidden = !isOpen;
        toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }

    function status(message, state) {
        var node = root && root.querySelector('[data-demo-status]');
        if (node) {
            node.textContent = message;
            node.dataset.state = state || 'idle';
        }
    }

    function allSteps() {
        var steps = [];
        (config.modules || []).forEach(function (module) {
            module.steps.forEach(function (step) {
                steps.push(Object.assign({
                    module_available: module.available,
                    module_disabled_reason: module.disabled_reason,
                }, step));
            });
        });
        return steps;
    }

    function moduleById(moduleId) {
        return (config.modules || []).find(function (module) {
            return module.id === moduleId;
        });
    }

    function stepsForModule(moduleId) {
        var module = moduleById(moduleId);
        if (!module || !module.available) {
            return [];
        }
        return module.steps.map(function (step) {
            return Object.assign({ module_available: true }, step);
        });
    }

    function checkboxNodes() {
        return Array.from(root.querySelectorAll('[data-demo-step-checkbox]'));
    }

    function selectedStepIds() {
        return checkboxNodes().filter(function (input) {
            return input.checked && !input.disabled;
        }).map(function (input) {
            return input.value;
        });
    }

    function selectedSteps() {
        var ids = selectedStepIds();
        return allSteps().filter(function (step) {
            return ids.indexOf(step.id) !== -1 && step.module_available;
        });
    }

    function updateSelectedCount() {
        var count = selectedStepIds().length;
        var node = root.querySelector('[data-demo-selected-count]');
        if (node) {
            node.textContent = count + ' selected';
        }
    }

    function persistSelection() {
        writeJson(SELECTED_KEY, selectedStepIds(), 'local');
        updateSelectedCount();
    }

    function setAllSelections(checked) {
        checkboxNodes().forEach(function (input) {
            if (!input.disabled) {
                input.checked = checked;
            }
        });
        persistSelection();
        status(checked ? 'All available demo steps selected.' : 'All demo step selections cleared.', checked ? 'success' : 'idle');
    }

    function paceDelay() {
        var select = root.querySelector('[data-demo-pace]');
        var paceId = select ? select.value : config.default_pace;
        var pace = (config.pace_options || []).find(function (item) {
            return item.id === paceId;
        });
        return pace ? pace.delay_ms : 1500;
    }
    function wait(milliseconds) {
        return new Promise(function (resolve) {
            window.setTimeout(resolve, milliseconds);
        });
    }

    function typingDelay() {
        var delay = paceDelay();
        if (delay <= 500) {
            return 20;
        }
        if (delay <= 900) {
            return 35;
        }
        if (delay <= 1600) {
            return 70;
        }
        return 110;
    }

    async function typeLikeCustomer(element, value, speed) {
        element.focus();
        element.value = '';

        for (var index = 0; index < String(value).length; index += 1) {
            element.value += String(value).charAt(index);
            element.dispatchEvent(new Event('input', { bubbles: true }));
            await wait(speed || typingDelay());
        }

        element.dispatchEvent(new Event('change', { bubbles: true }));
    }

    async function waitForElement(selector, timeout) {
        var startedAt = Date.now();
        var maxWait = timeout || 10000;

        while (Date.now() - startedAt < maxWait) {
            var element = document.querySelector(selector);
            if (element) {
                return element;
            }
            await wait(150);
        }

        throw new Error('Demo Bot could not find: ' + selector);
    }

    function buildDemoCustomer() {
        var uniqueId = Date.now();
        return {
            firstName: 'Maria',
            lastName: 'Santos',
            email: 'maria.santos.' + uniqueId + '@example.com',
            username: 'maria' + uniqueId,
            password: 'DemoCustomer123!',
            phone: '09123456789',
        };
    }

    function storeDemoCustomer(demoCustomer) {
        writeJson('hanilies.demoCustomer', demoCustomer, 'session');
        writeJson('hanilies.demoCustomer', demoCustomer, 'local');
        writeJson('demoCustomer', demoCustomer, 'session');
    }

    function readStoredDemoCustomer() {
        return readJson('hanilies.demoCustomer', null, 'session') || readJson('hanilies.demoCustomer', null, 'local') || readJson('demoCustomer', null, 'session');
    }

    function activeDemoContact() {
        var demoCustomer = readStoredDemoCustomer();
        if (demoCustomer) {
            return demoCustomer;
        }
        return {
            firstName: 'Maria',
            lastName: 'Santos',
            email: 'maria.demo@example.com',
            phone: '09123456789',
        };
    }

    function isAdminSessionReady() {
        return Boolean(config && config.session && config.session.is_admin);
    }

    function isCustomerSignedIn() {
        return Boolean(
            (config && config.session && config.session.is_authenticated) ||
            document.querySelector('a[href*="logout"], a[href*="profile"], [data-demo="customer-session-ready"]')
        );
    }

    function stepAlreadySatisfied(step) {
        if (step.id === 'customer_login') {
            return isCustomerSignedIn();
        }
        if (step.id === 'administrator_login') {
            return isAdminSessionReady();
        }
        return false;
    }

    function getCsrfToken() {
        var cookieMatch = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        if (cookieMatch) {
            return decodeURIComponent(cookieMatch[1]);
        }
        var csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
        return csrfInput ? csrfInput.value : '';
    }

    function setFieldValue(element, value) {
        if (!element) {
            return;
        }
        element.focus();
        element.value = value;
        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function focusFieldForDemo(element) {
        if (!element) {
            return;
        }
        element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        element.focus();
    }

    async function fillDemoField(element, value, label, speed, pauseAfter) {
        if (!element) {
            return;
        }
        status('Registration demo: filling ' + label + '...', 'loading');
        focusFieldForDemo(element);
        await wait(220);
        await typeLikeCustomer(element, value, speed);
        await wait(pauseAfter || 220);
    }

    function fallbackDateString() {
        var futureDate = new Date();
        futureDate.setDate(futureDate.getDate() + 4);
        return futureDate.toISOString().slice(0, 10);
    }

    function pickDateValue(input) {
        if (!input) {
            return fallbackDateString();
        }
        return input.min || input.value || fallbackDateString();
    }

    function selectFirstNonEmptyOption(select) {
        if (!select) {
            return null;
        }
        var option = Array.from(select.options || []).find(function (item) {
            return item.value;
        });
        if (!option) {
            return null;
        }
        setFieldValue(select, option.value);
        return option.value;
    }

    function ensureSelectValue(select) {
        if (!select) {
            return null;
        }
        if (select.value) {
            return select.value;
        }
        return selectFirstNonEmptyOption(select);
    }

    function ensureRadioSelection(scope, name, preferredValue) {
        var selector = 'input[name="' + name + '"]';
        var candidates = Array.from((scope || document).querySelectorAll(selector)).filter(function (input) {
            return !input.disabled;
        });
        if (!candidates.length) {
            return null;
        }
        var preferred = candidates.find(function (input) {
            return input.value === preferredValue;
        });
        var chosen = preferred || candidates.find(function (input) {
            return input.checked;
        }) || candidates[0];
        if (!chosen.checked) {
            chosen.click();
            chosen.dispatchEvent(new Event('change', { bubbles: true }));
        }
        return chosen;
    }

    function ensureCheckboxSelection(scope, name) {
        var firstCheckbox = (scope || document).querySelector('input[name="' + name + '"]');
        if (firstCheckbox && !firstCheckbox.checked) {
            firstCheckbox.click();
            firstCheckbox.dispatchEvent(new Event('change', { bubbles: true }));
        }
        return firstCheckbox;
    }

    function uniqueReference(prefix) {
        return (prefix + '-' + Date.now()).toUpperCase();
    }

    function buildReceiptFile(referenceNumber, amount) {
        return new Promise(function (resolve, reject) {
            var canvas = document.createElement('canvas');
            canvas.width = 1200;
            canvas.height = 700;
            var context = canvas.getContext('2d');

            if (!context || typeof canvas.toBlob !== 'function') {
                reject(new Error('Demo Bot could not generate the payment receipt image.'));
                return;
            }

            context.fillStyle = '#ffffff';
            context.fillRect(0, 0, canvas.width, canvas.height);
            context.fillStyle = '#1d1d1f';
            context.font = 'bold 34px sans-serif';
            context.fillText('GCash Receipt', 48, 74);
            context.font = '24px sans-serif';
            context.fillText('Merchant: Hanilies Cakeshoppe', 48, 150);
            context.fillText('Reference No: ' + referenceNumber, 48, 208);
            context.fillText('Amount Paid: P' + amount, 48, 266);
            context.fillText('Status: Successful', 48, 324);
            context.fillText('Prepared automatically by the live demo bot.', 48, 382);

            canvas.toBlob(function (blob) {
                if (!blob) {
                    reject(new Error('Demo Bot could not generate the payment receipt image.'));
                    return;
                }
                resolve(new File([blob], 'hanilies-demo-receipt.png', { type: 'image/png' }));
            }, 'image/png');
        });
    }

    async function assignFile(input, file) {
        if (!input) {
            return;
        }
        var transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
        input.dispatchEvent(new Event('change', { bubbles: true }));
        await wait(180);
    }

    async function runDemoSessionAction(action) {
        var sessionConfig = config && config.session_endpoints;
        var sessionUrl = sessionConfig && sessionConfig.manage_session;
        if (!sessionUrl) {
            throw new Error('Demo Bot session management is unavailable.');
        }

        var response = await fetch(sessionUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-CSRFToken': getCsrfToken(),
                'Accept': 'application/json'
            },
            body: new URLSearchParams({ action: action }).toString()
        });

        if (!response.ok) {
            throw new Error('Demo Bot could not change the session state.');
        }

        return response.json();
    }

    async function runCustomerRegistration(state) {
        if (state.registrationSubmitted) {
            return false;
        }

        var demoCustomer = buildDemoCustomer();
        var speed = typingDelay();
        status('Opening the registration form and filling it like a live customer demo...', 'loading');

        var firstNameField = await waitForElement('[data-demo="register-first-name"], #registerForm input[name="firstname"], input[name="first_name"], #id_first_name');
        var lastNameField = await waitForElement('[data-demo="register-last-name"], #registerForm input[name="lastname"], input[name="last_name"], #id_last_name');
        var emailField = await waitForElement('[data-demo="register-email"], #registerForm input[name="email"], #id_email');
        var usernameField = await waitForElement('[data-demo="register-username"], #registerForm input[name="username"], #id_username');
        var passwordField = await waitForElement('[data-demo="register-password"], #registerForm input[name="password"], input[name="password1"], #password, #id_password1');
        var confirmPasswordField = await waitForElement('[data-demo="register-confirm-password"], #registerForm input[name="confirm_password"], input[name="password2"], #confirm_password, #id_password2');
        var phoneField = await waitForElement('[data-demo="register-phone"], #registerForm input[name="phone"], #phone, #id_phone');
        var termsCheckbox = await waitForElement('[data-demo="register-terms"], #registerForm #terms, input[name="terms"], input[type="checkbox"]');
        var submitButton = await waitForElement('[data-demo="register-submit"], #registerForm #submitBtn, button[type="submit"]');

        await fillDemoField(firstNameField, demoCustomer.firstName, 'first name', speed, 150);
        await fillDemoField(lastNameField, demoCustomer.lastName, 'last name', speed, 150);
        await fillDemoField(emailField, demoCustomer.email, 'email address', speed, 180);
        await fillDemoField(usernameField, demoCustomer.username, 'username', speed, 180);
        await fillDemoField(passwordField, demoCustomer.password, 'password', speed, 220);
        await fillDemoField(confirmPasswordField, demoCustomer.password, 'confirm password', speed, 220);
        await fillDemoField(phoneField, demoCustomer.phone, 'phone number', speed, 260);

        if (!termsCheckbox.checked) {
            status('Registration demo: accepting the terms and conditions...', 'loading');
            termsCheckbox.scrollIntoView({ behavior: 'smooth', block: 'center' });
            await wait(350);
            termsCheckbox.click();
            termsCheckbox.dispatchEvent(new Event('change', { bubbles: true }));
            await wait(500);
        }

        storeDemoCustomer(demoCustomer);
        state.registrationSubmitted = true;
        state.pendingStepId = null;
        state.index += 1;
        setState(state);

        status('Registration demo: submitting the completed customer account form...', 'loading');
        submitButton.scrollIntoView({ behavior: 'smooth', block: 'center' });
        await wait(700);
        submitButton.click();
        return true;
    }

    async function runCustomerLogin(state) {
        if (state.loginSubmitted) {
            return false;
        }

        var demoCustomer = readStoredDemoCustomer();
        if (!demoCustomer) {
            finishDemo('The demo customer session details were lost. Restart the customer flow.', 'error');
            return true;
        }

        var speed = typingDelay();
        status('Signing the demo customer back in...', 'loading');

        var usernameField = await waitForElement('[data-demo="login-username"], input[name="username"], #id_username');
        var passwordField = await waitForElement('[data-demo="login-password"], input[name="password"], #password, #id_password');
        var submitButton = await waitForElement('[data-demo="login-submit"], button[type="submit"], input[type="submit"]');
        var form = usernameField.form || submitButton.form || document.querySelector('form');

        await typeLikeCustomer(usernameField, demoCustomer.username, speed);
        await typeLikeCustomer(passwordField, demoCustomer.password, speed);

        state.loginSubmitted = true;
        state.pendingStepId = null;
        state.index += 1;
        setState(state);

        status('Submitting the demo customer login...', 'loading');
        await wait(500);
        if (form && typeof form.submit === 'function') {
            form.submit();
        } else {
            submitButton.click();
        }
        return true;
    }

    async function runCakeCheckout(state) {
        if (state.cakeOrderSubmitted) {
            return false;
        }

        var demoCustomer = activeDemoContact();
        var form = await waitForElement('#cake-order-form');
        status('Filling the live cake order form...', 'loading');

        ensureSelectValue(form.querySelector('select[name="theme"]'));
        ensureRadioSelection(form, 'tier');
        ensureRadioSelection(form, 'size');
        ensureRadioSelection(form, 'shape');
        ensureRadioSelection(form, 'flavor');
        ensureCheckboxSelection(form, 'frosting');
        ensureCheckboxSelection(form, 'filling');
        ensureCheckboxSelection(form, 'decorations');

        setFieldValue(form.querySelector('input[name="color_palette"]'), 'Blush pink and gold');
        setFieldValue(form.querySelector('input[name="message_on_cake"]'), 'Happy Birthday Maria');
        setFieldValue(form.querySelector('input[name="quantity"]'), '1');
        setFieldValue(form.querySelector('input[name="delivery_date"]'), pickDateValue(form.querySelector('input[name="delivery_date"]')));
        setFieldValue(form.querySelector('input[name="delivery_street_address"]'), '123 Mabini Street');
        setFieldValue(form.querySelector('input[name="delivery_barangay"]'), 'Poblacion 1');
        ensureSelectValue(form.querySelector('select[name="delivery_city"]'));
        setFieldValue(form.querySelector('input[name="delivery_landmark"]'), 'Near the municipal hall');
        setFieldValue(form.querySelector('textarea[name="special_instructions"]'), 'Please keep the frosting details neat for the live demo.');
        setFieldValue(form.querySelector('input[name="contact_name"]'), demoCustomer.firstName + ' ' + demoCustomer.lastName);
        setFieldValue(form.querySelector('input[name="contact_phone"]'), demoCustomer.phone);
        setFieldValue(form.querySelector('input[name="contact_email"]'), demoCustomer.email);
        ensureRadioSelection(form, 'payment_method', 'cod');

        var cakeReferenceInput = form.querySelector('input[name="reference_number"]');
        var cakePaymentAmountInput = form.querySelector('input[name="payment_amount"]');
        var cakeProofInput = form.querySelector('input[name="proof_image"]');
        var cakeReferenceNumber = uniqueReference('HANI-CAKE');
        setFieldValue(cakeReferenceInput, cakeReferenceNumber);
        await assignFile(cakeProofInput, await buildReceiptFile(cakeReferenceNumber, cakePaymentAmountInput ? cakePaymentAmountInput.value : '0.00'));

        state.cakeOrderSubmitted = true;
        state.pendingStepId = null;
        state.index += 1;
        setState(state);

        status('Submitting the live cake order...', 'loading');
        await wait(650);
        form.submit();
        return true;
    }

    async function runPackageSelection(state) {
        if (state.packageSelectionSubmitted) {
            return false;
        }

        var form = await waitForElement('#package-step-one');
        status('Submitting the package selection step...', 'loading');

        state.packageSelectionSubmitted = true;
        state.pendingStepId = null;
        state.index += 1;
        setState(state);

        await wait(500);
        form.submit();
        return true;
    }

    async function runPackageCakeDesign(state) {
        if (state.packageCakeDesignSubmitted) {
            return false;
        }

        var form = await waitForElement('#package-step-two');
        status('Customizing the package cake options...', 'loading');

        ensureSelectValue(form.querySelector('select[name="theme"]'));
        ensureRadioSelection(form, 'cake_size');
        ensureRadioSelection(form, 'shape');
        ensureRadioSelection(form, 'flavor');
        ensureCheckboxSelection(form, 'frosting');
        ensureCheckboxSelection(form, 'filling');
        ensureCheckboxSelection(form, 'cake_decorations');
        setFieldValue(form.querySelector('input[name="color_palette"]'), 'Ivory, blush, and gold');
        setFieldValue(form.querySelector('input[name="message_on_cake"]'), 'Welcome to the celebration');
        setFieldValue(form.querySelector('textarea[name="cake_instructions"]'), 'Use the default package cake styling for the demo walkthrough.');

        state.packageCakeDesignSubmitted = true;
        state.pendingStepId = null;
        state.index += 1;
        setState(state);

        await wait(550);
        form.submit();
        return true;
    }

    async function runPackagePayment(state) {
        if (state.packagePaymentSubmitted) {
            return false;
        }

        var demoCustomer = activeDemoContact();
        var form = await waitForElement('#package-step-three');
        status('Filling the final package booking and payment details...', 'loading');

        setFieldValue(form.querySelector('input[name="event_date"]'), pickDateValue(form.querySelector('input[name="event_date"]')));
        setFieldValue(form.querySelector('input[name="event_time"]'), '10:00');
        setFieldValue(form.querySelector('textarea[name="venue"]'), '123 Mabini Street, Poblacion 1');
        setFieldValue(form.querySelector('input[name="contact_name"]'), demoCustomer.firstName + ' ' + demoCustomer.lastName);
        setFieldValue(form.querySelector('input[name="contact_phone"]'), demoCustomer.phone);
        setFieldValue(form.querySelector('input[name="contact_email"]'), demoCustomer.email);
        ensureRadioSelection(form, 'payment_method', 'cod');

        var packageReferenceInput = form.querySelector('input[name="reference_number"]');
        var packagePaymentAmountInput = form.querySelector('input[name="payment_amount"]');
        var packageProofInput = form.querySelector('input[name="proof_image"]');
        var packageReferenceNumber = uniqueReference('HANI-PKG');
        setFieldValue(packageReferenceInput, packageReferenceNumber);
        await assignFile(packageProofInput, await buildReceiptFile(packageReferenceNumber, packagePaymentAmountInput ? packagePaymentAmountInput.value : '0.00'));

        state.packagePaymentSubmitted = true;
        state.pendingStepId = null;
        state.index += 1;
        setState(state);

        status('Submitting the live package booking...', 'loading');
        await wait(650);
        form.submit();
        return true;
    }

    async function runAdministratorLogin(state) {
        if (state.adminSessionStarted) {
            return false;
        }

        try {
            status('Switching into the isolated demo admin session...', 'loading');
            var nextStep = state.steps[state.index + 1];
            var sessionResponse = await runDemoSessionAction(config.session_endpoints.actions.start_admin);

            state.adminSessionStarted = true;
            state.pendingStepId = null;
            state.index += 1;
            setState(state);

            window.location.href = (nextStep && nextStep.url) || sessionResponse.redirect_url || step.url;
            return true;
        } catch (error) {
            finishDemo(error.message || 'Demo Bot could not start the administrator session.', 'error');
            return true;
        }
    }

    async function runDemoLogout(state, step) {
        try {
            status('Signing out of the demo administrator session...', 'loading');
            await runDemoSessionAction(config.session_endpoints.actions.logout);

            state.pendingStepId = null;
            state.index += 1;
            setState(state);

            window.location.href = step.url;
            return true;
        } catch (error) {
            finishDemo(error.message || 'Demo Bot could not end the administrator session.', 'error');
            return true;
        }
    }

    async function runStepAutomation(state, step) {
        if (stepAlreadySatisfied(step)) {
            status(step.id === 'administrator_login' ? 'Administrator session is already ready. Continuing...' : 'Customer session is already registered and signed in. Continuing...', 'success');
            state.pendingStepId = null;
            state.index += 1;
            setState(state);
            runningTimer = window.setTimeout(resumeDemo, 450);
            return true;
        }

        if (step.id === 'customer_registration') {
            try {
                return await runCustomerRegistration(state);
            } catch (error) {
                finishDemo(error.message || 'Demo Bot could not complete customer registration.', 'error');
                return true;
            }
        }

        if (step.id === 'customer_login') {
            try {
                return await runCustomerLogin(state);
            } catch (error) {
                finishDemo(error.message || 'Demo Bot could not complete customer login.', 'error');
                return true;
            }
        }

        if (step.id === 'customize_cake') {
            try {
                return await runCakeCheckout(state);
            } catch (error) {
                finishDemo(error.message || 'Demo Bot could not complete the cake order.', 'error');
                return true;
            }
        }

        if (step.id === 'customize_package_cake') {
            try {
                return await runPackageSelection(state);
            } catch (error) {
                finishDemo(error.message || 'Demo Bot could not complete the package selection step.', 'error');
                return true;
            }
        }

        if (step.id === 'package_cake_design') {
            try {
                return await runPackageCakeDesign(state);
            } catch (error) {
                finishDemo(error.message || 'Demo Bot could not complete the package cake customization step.', 'error');
                return true;
            }
        }

        if (step.id === 'simulated_payment') {
            try {
                return await runPackagePayment(state);
            } catch (error) {
                finishDemo(error.message || 'Demo Bot could not complete the package payment step.', 'error');
                return true;
            }
        }

        if (step.id === 'administrator_login') {
            return runAdministratorLogin(state);
        }

        if (step.id === 'logout') {
            return runDemoLogout(state, step);
        }

        return false;
    }

    function removeFocusNodes() {
        if (highlightNode) {
            highlightNode.remove();
            highlightNode = null;
        }
        if (calloutNode) {
            calloutNode.remove();
            calloutNode = null;
        }
    }

    function findTarget(selector) {
        var selectors = (selector || 'body').split(',').map(function (item) {
            return item.trim();
        }).filter(Boolean);
        for (var i = 0; i < selectors.length; i += 1) {
            var target = document.querySelector(selectors[i]);
            if (target) {
                return target;
            }
        }
        return document.body;
    }

    function placeFocus(step, target) {
        var rect = target.getBoundingClientRect();
        var top = Math.max(8, rect.top - 8);
        var left = Math.max(8, rect.left - 8);
        var width = Math.min(window.innerWidth - left - 8, rect.width + 16);
        var height = Math.min(window.innerHeight - top - 8, rect.height + 16);

        highlightNode = document.createElement('div');
        highlightNode.className = 'new-demo-bot__highlight';
        highlightNode.style.top = top + 'px';
        highlightNode.style.left = left + 'px';
        highlightNode.style.width = Math.max(80, width) + 'px';
        highlightNode.style.height = Math.max(48, height) + 'px';

        calloutNode = document.createElement('div');
        calloutNode.className = 'new-demo-bot__callout';
        calloutNode.innerHTML = '<strong></strong><span></span><div class="new-demo-bot__callout-actions"><button type="button" data-demo-next-step>Next Step</button><button type="button" data-demo-stop-inline>Stop</button></div>';
        calloutNode.querySelector('strong').textContent = step.title;
        calloutNode.querySelector('span').textContent = step.message;
        calloutNode.querySelector('[data-demo-next-step]').addEventListener('click', function () {
            window.clearTimeout(runningTimer);
            runningTimer = null;
            resumeDemo();
        });
        calloutNode.querySelector('[data-demo-stop-inline]').addEventListener('click', function () {
            stopDemo('Demo stopped.');
        });

        var calloutTop = top + Math.min(height + 14, window.innerHeight - top - 130);
        if (calloutTop > window.innerHeight - 150) {
            calloutTop = Math.max(12, top - 150);
        }
        calloutNode.style.top = calloutTop + 'px';
        calloutNode.style.left = Math.max(12, Math.min(left, window.innerWidth - 350)) + 'px';
        document.body.appendChild(highlightNode);
        document.body.appendChild(calloutNode);
    }

    function showFocus(step) {
        removeFocusNodes();
        var target = findTarget(step.selector);
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        window.setTimeout(function () {
            var state = getState();
            if (state && state.running && isRunning) {
                removeFocusNodes();
                placeFocus(step, target);
            }
        }, 260);
    }

    function stopDemo(message) {
        window.clearTimeout(runningTimer);
        runningTimer = null;
        isRunning = false;
        clearState();
        removeFocusNodes();
        status(message || 'Demo stopped.', 'idle');
    }

    function runSteps(steps, label) {
        if (!steps.length) {
            status('Choose at least one available step first.', 'error');
            return;
        }
        window.clearTimeout(runningTimer);
        runningTimer = null;
        isRunning = true;
        setPanelOpen(true);
        setState({
            running: true,
            version: config.version,
            label: label,
            index: 0,
            steps: steps,
            pendingStepId: null,
            startedAt: Date.now(),
        });
        resumeDemo();
    }

    function finishDemo(message, state) {
        stopDemo(message);
        status(message, state || 'idle');
    }

    function canRunBeforeRouteMatch(step) {
        return step && (step.id === 'administrator_login' || step.id === 'logout');
    }

    async function resumeDemo() {
        var state = getState();
        if (!state || !state.running || !state.steps) {
            isRunning = false;
            status('Ready. Start the full guided demo or run a selected presentation flow.', 'idle');
            return;
        }
        isRunning = true;
        setPanelOpen(true);
        if (state.version !== config.version) {
            finishDemo('Demo was updated. Start again with the latest presentation script.', 'error');
            return;
        }
        if (state.startedAt && Date.now() - state.startedAt > MAX_RUN_TIME) {
            finishDemo('Demo expired after 15 minutes. Start again when ready.', 'error');
            return;
        }
        if (state.index >= state.steps.length) {
            finishDemo('Demo complete. The selected presentation flow finished successfully.', 'success');
            return;
        }

        var step = state.steps[state.index];
        if (stepAlreadySatisfied(step)) {
            await runStepAutomation(state, step);
            return;
        }
        if (canRunBeforeRouteMatch(step)) {
            await runStepAutomation(state, step);
            return;
        }
        if (!samePath(step.url)) {
            if (state.pendingStepId === step.id) {
                finishDemo('Demo paused because "' + step.title + '" could not open. Please sign in or check access, then run this flow again.', 'error');
                return;
            }
            state.pendingStepId = step.id;
            setState(state);
            status('Opening ' + step.title + '...', 'loading');
            window.location.href = step.url;
            return;
        }

        state.pendingStepId = null;
        status('Running ' + state.label + ' (' + (state.index + 1) + ' of ' + state.steps.length + '): ' + step.title, 'loading');
        if (await runStepAutomation(state, step)) {
            return;
        }
        showFocus(step);
        state.index += 1;
        setState(state);
        runningTimer = window.setTimeout(resumeDemo, paceDelay());
    }

    function renderPaceOptions() {
        var select = root.querySelector('[data-demo-pace]');
        if (!select) {
            return;
        }
        select.innerHTML = '';
        (config.pace_options || []).forEach(function (pace) {
            var option = document.createElement('option');
            option.value = pace.id;
            option.textContent = pace.label;
            option.selected = pace.id === config.default_pace;
            select.appendChild(option);
        });
    }

    function renderScript() {
        var container = root.querySelector('[data-demo-script]');
        var saved = readJson(SELECTED_KEY, null, 'local');
        var savedIds = Array.isArray(saved) ? saved : null;
        container.innerHTML = '';

        allSteps().forEach(function (step) {
            var checkedByDefault = step.module_available && (!savedIds || savedIds.indexOf(step.id) !== -1);
            var id = 'new-demo-step-' + step.id;
            var card = document.createElement('label');
            card.className = 'new-demo-bot__script-card';
            if (!step.module_available) {
                card.classList.add('new-demo-bot__script-card--locked');
            }
            card.setAttribute('for', id);
            card.innerHTML = '<input type="checkbox" data-demo-step-checkbox><span><strong class="new-demo-bot__script-title"></strong><span class="new-demo-bot__script-message"></span></span>';
            var input = card.querySelector('input');
            input.id = id;
            input.value = step.id;
            input.disabled = !step.module_available;
            input.checked = checkedByDefault;
            card.querySelector('.new-demo-bot__script-title').textContent = step.title;
            card.querySelector('.new-demo-bot__script-message').textContent = step.module_available ? step.message : step.module_disabled_reason;
            input.addEventListener('change', persistSelection);
            container.appendChild(card);
        });
        persistSelection();
    }

    function setAvailabilityState(button, available, availableTitle, disabledReason) {
        if (!button) {
            return;
        }
        button.disabled = false;
        button.setAttribute('aria-disabled', available ? 'false' : 'true');
        button.title = available ? availableTitle : disabledReason;
    }

    function setFlowButtonStates() {
        var admin = moduleById('admin');
        setAvailabilityState(
            root.querySelector('[data-demo-run-full]'),
            config.full_demo.available,
            'Run Full Demo Flow',
            config.full_demo.disabled_reason
        );
        setAvailabilityState(
            root.querySelector('[data-demo-run-flow="admin"]'),
            admin && admin.available,
            'Run Admin Flow',
            admin ? admin.disabled_reason : 'This flow is unavailable.'
        );
    }

    function bindControls() {
        root.querySelector('[data-demo-toggle]').addEventListener('click', function () {
            setPanelOpen(panel().hidden);
        });
        root.querySelector('[data-demo-close]').addEventListener('click', function () {
            setPanelOpen(false);
        });
        root.querySelector('[data-demo-stop]').addEventListener('click', function () {
            stopDemo('Demo stopped.');
        });
        root.querySelector('[data-demo-select-all]').addEventListener('click', function () {
            setAllSelections(true);
        });
        root.querySelector('[data-demo-clear-all]').addEventListener('click', function () {
            setAllSelections(false);
        });
        root.querySelector('[data-demo-run-full]').addEventListener('click', function () {
            if (!config.full_demo.available) {
                status(config.full_demo.disabled_reason, 'error');
                return;
            }
            runSteps(config.full_demo.steps, config.full_demo.title);
        });
        root.querySelector('[data-demo-run-selected]').addEventListener('click', function () {
            runSteps(selectedSteps(), 'Selected Demo');
        });
        root.querySelectorAll('[data-demo-run-flow]').forEach(function (button) {
            button.addEventListener('click', function () {
                var moduleId = button.dataset.demoRunFlow;
                var module = moduleById(moduleId);
                if (!module || !module.available) {
                    status(module ? module.disabled_reason : 'This flow is unavailable.', 'error');
                    return;
                }
                runSteps(stepsForModule(moduleId), module.title);
            });
        });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && isRunning) {
                stopDemo('Demo stopped with Escape.');
            }
        });
    }

    function init() {
        root = document.querySelector('[data-new-demo-bot]');
        if (!root || !window.fetch || !window.localStorage || !window.sessionStorage) {
            return;
        }
        cleanupOldDemoState();
        fetch(root.dataset.configUrl, { headers: { Accept: 'application/json' } })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error('Unable to load demo config.');
                }
                return response.json();
            })
            .then(function (payload) {
                config = payload;
                renderPaceOptions();
                renderScript();
                setFlowButtonStates();
                bindControls();
                resumeDemo();
            })
            .catch(function () {
                status('Demo bot could not load its presentation script. Refresh and try again.', 'error');
            });
    }

    document.addEventListener('DOMContentLoaded', init);
}());