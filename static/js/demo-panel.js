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
    const quickButtons = Array.from(panel.querySelectorAll('.demo-trigger'));
    const customButton = document.getElementById('demo-custom-script-trigger');
    const stopButton = document.getElementById('demo-stop-trigger');
    const voiceToggle = document.getElementById('voice-demo-toggle');
    const delaySelect = document.getElementById('demo-delay');
    const paymentModeSelect = document.getElementById('demo-payment-mode');
    const scriptSteps = Array.from(panel.querySelectorAll('.demo-script-step'));
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const browserDemoStorageKey = 'haniliesRemoteBrowserDemo';
    let isLaunching = false;
    let isStopping = false;
    let isListening = false;
    let recognition = null;
    let lastRunningState = false;
    let browserDemoTimer = null;

    const browserStepMessages = {
        home: 'Opening the homepage for the defense walkthrough...',
        login: 'Logging in with the panel demo account...',
        ai_recommendations: 'Showing personalized recommendations for the demo account...',
        cakes: 'Showing the live cake catalog...',
        cake_order: 'Opening the cake customization page...',
        cake_tracking: 'Showing the demo cake order tracking page...',
        packages: 'Showing the live package catalog...',
        package_order: 'Opening the package order flow...',
        package_tracking: 'Showing the demo package tracking page...',
        profile: 'Showing the demo customer profile...',
        order_tracking: 'Opening the full tracking dashboard...',
        about: 'Opening the about page...',
        contact: 'Opening the contact page...'
    };

    function setStatus(message, state) {
        statusNode.textContent = message;
        statusNode.dataset.state = state;
    }

    function loadBrowserDemoPlan() {
        try {
            const rawValue = window.sessionStorage.getItem(browserDemoStorageKey);
            return rawValue ? JSON.parse(rawValue) : null;
        } catch (error) {
            return null;
        }
    }

    function saveBrowserDemoPlan(plan) {
        window.sessionStorage.setItem(browserDemoStorageKey, JSON.stringify(plan));
    }

    function clearBrowserDemoPlan() {
        window.sessionStorage.removeItem(browserDemoStorageKey);
        if (browserDemoTimer) {
            window.clearTimeout(browserDemoTimer);
            browserDemoTimer = null;
        }
    }

    function locationMatchesTarget(targetUrl) {
        if (!targetUrl) {
            return false;
        }

        const target = new URL(targetUrl, window.location.origin);
        if (target.pathname !== window.location.pathname) {
            return false;
        }

        if (target.search) {
            return target.search === window.location.search;
        }

        return true;
    }

    function getCurrentBrowserStep(plan) {
        return Array.isArray(plan.script_steps) ? plan.script_steps[plan.currentIndex] : null;
    }

    async function finishBrowserDemo(message) {
        clearBrowserDemoPlan();
        try {
            await fetch(stopEndpoint, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfTokenInput ? csrfTokenInput.value : '',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
        } catch (error) {
            // Ignore stop errors here; the local browser state is already cleared.
        }

        setStatus(message, 'success');
        speak(message);
        setControlState(false);
    }

    function advanceBrowserDemo(plan) {
        const nextIndex = (plan.currentIndex || 0) + 1;
        if (!Array.isArray(plan.script_steps) || nextIndex >= plan.script_steps.length) {
            finishBrowserDemo('Defense demo finished. You can start another walkthrough anytime.');
            return;
        }

        plan.currentIndex = nextIndex;
        plan.loginSubmitted = false;
        saveBrowserDemoPlan(plan);

        const nextStep = getCurrentBrowserStep(plan);
        const nextUrl = plan.step_urls ? plan.step_urls[nextStep] : null;
        if (!nextUrl) {
            finishBrowserDemo('Defense demo finished. You can start another walkthrough anytime.');
            return;
        }

        window.location.assign(nextUrl);
    }

    function scheduleBrowserDemoAction(callback, delay) {
        if (browserDemoTimer) {
            return;
        }

        browserDemoTimer = window.setTimeout(() => {
            browserDemoTimer = null;
            callback();
        }, delay);
    }

    function maybeRunBrowserDemo() {
        const plan = loadBrowserDemoPlan();
        if (!plan || plan.mode !== 'browser') {
            return;
        }

        const currentStep = getCurrentBrowserStep(plan);
        if (!currentStep) {
            finishBrowserDemo('Defense demo finished. You can start another walkthrough anytime.');
            return;
        }

        setStatus(browserStepMessages[currentStep] || 'Running the defense walkthrough...', 'loading');
        lastRunningState = true;
        setControlState(true);

        if (currentStep === 'login' && plan.loginSubmitted && window.location.pathname !== '/login/') {
            advanceBrowserDemo(plan);
            return;
        }

        const targetUrl = plan.step_urls ? plan.step_urls[currentStep] : null;
        if (currentStep !== 'login' && !locationMatchesTarget(targetUrl)) {
            window.location.assign(targetUrl);
            return;
        }

        if (currentStep === 'login') {
            if (!locationMatchesTarget(targetUrl)) {
                window.location.assign(targetUrl);
                return;
            }

            const usernameInput = document.querySelector('input[name="username"]');
            const passwordInput = document.querySelector('input[name="password"]');
            const loginForm = usernameInput ? usernameInput.form : null;
            if (!usernameInput || !passwordInput || !loginForm) {
                setStatus('Unable to find the login form for the browser demo.', 'error');
                return;
            }

            scheduleBrowserDemoAction(() => {
                usernameInput.value = plan.credentials.username;
                passwordInput.value = plan.credentials.password;
                usernameInput.dispatchEvent(new Event('input', { bubbles: true }));
                passwordInput.dispatchEvent(new Event('input', { bubbles: true }));
                plan.loginSubmitted = true;
                saveBrowserDemoPlan(plan);
                loginForm.submit();
            }, 1200);
            return;
        }

        const holdDuration = currentStep === 'home' || currentStep === 'ai_recommendations' ? 3200 : 2400;
        scheduleBrowserDemoAction(() => {
            advanceBrowserDemo(plan);
        }, holdDuration);
    }

    function speak(message) {
        if (!('speechSynthesis' in window)) {
            return;
        }
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(message);
        utterance.rate = 1;
        utterance.pitch = 1;
        window.speechSynthesis.speak(utterance);
    }

    function selectedScriptSteps() {
        return scriptSteps
            .filter((step) => step.checked)
            .map((step) => step.value);
    }

    function payloadForScenario(scenario, customSteps) {
        return {
            scenario,
            script_steps: customSteps,
            delay: parseFloat(delaySelect.value || '1.1'),
            narrate: true,
            close_browser: true,
            hold_seconds: 20,
            headless: false,
            browser: 'auto',
            payment_mode: paymentModeSelect.value || 'gcash'
        };
    }

    function setControlState(isRunning) {
        lastRunningState = isRunning;
        quickButtons.forEach((button) => {
            button.disabled = isRunning || isLaunching || isStopping;
        });
        customButton.disabled = isRunning || isLaunching || isStopping;
        scriptSteps.forEach((step) => {
            step.disabled = isRunning || isLaunching || isStopping;
        });
        delaySelect.disabled = isRunning || isLaunching || isStopping;
        paymentModeSelect.disabled = isRunning || isLaunching || isStopping;
        stopButton.disabled = !isRunning || isLaunching || isStopping;
        if (voiceToggle) {
            voiceToggle.disabled = isRunning || isLaunching || isStopping || !SpeechRecognition;
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

    async function startDemo(scenario, source, customSteps) {
        if (isLaunching || isStopping || lastRunningState) {
            return;
        }

        if (scenario === 'custom' && !customSteps.length) {
            setStatus('Choose at least one custom script step before starting the demo.', 'error');
            speak('Choose at least one custom script step before starting the demo.');
            return;
        }

        isLaunching = true;
        setControlState(false);
        setStatus(`Starting the ${scenario} demo...`, 'loading');

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

            if (data.mode === 'browser' && data.browser_demo) {
                const browserPlan = {
                    ...data.browser_demo,
                    mode: 'browser',
                    currentIndex: 0,
                    loginSubmitted: false
                };
                saveBrowserDemoPlan(browserPlan);
                const confirmation = source === 'voice'
                    ? `Voice command received. ${data.message}`
                    : data.message;
                setStatus(confirmation, 'success');
                speak(confirmation);
                setControlState(true);
                window.location.assign(browserPlan.launch_url);
                return;
            }

            const confirmation = source === 'voice'
                ? `Voice command received. ${data.message}`
                : data.message;
            setStatus(confirmation, 'success');
            speak(confirmation);
            setControlState(true);
        } catch (error) {
            setStatus(error.message, 'error');
            speak(error.message);
            setControlState(false);
        } finally {
            isLaunching = false;
        }
    }

    async function stopDemo(source) {
        if (isStopping || isLaunching || !lastRunningState) {
            return;
        }

        isStopping = true;
        setControlState(true);
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

            clearBrowserDemoPlan();

            setStatus(data.message, 'success');
            if (source === 'voice') {
                speak('Stopping the demo now.');
            }
            setControlState(false);
        } catch (error) {
            setStatus(error.message, 'error');
            speak(error.message);
            setControlState(true);
        } finally {
            isStopping = false;
        }
    }

    function describeActiveDemo(activeDemo) {
        if (!activeDemo) {
            return 'A demo bot is currently running.';
        }
        if (activeDemo.scenario === 'custom' && Array.isArray(activeDemo.script_steps) && activeDemo.script_steps.length) {
            return `Running a custom demo with ${activeDemo.script_steps.length} scripted step(s).`;
        }
        return `Running the ${activeDemo.scenario} demo now.`;
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

            if (!data.running && loadBrowserDemoPlan()) {
                clearBrowserDemoPlan();
            }

            if (data.running) {
                setStatus(describeActiveDemo(data.active_demo), 'loading');
                setControlState(true);
                return;
            }

            if (lastRunningState && !isLaunching && !isStopping) {
                setStatus('Demo finished. You can start another run or launch a custom script.', 'success');
            }
            setControlState(false);
        } catch (error) {
            if (!isLaunching && !isStopping) {
                setStatus('Unable to refresh demo status right now.', 'error');
            }
        }
    }

    function normalizeVoiceCommand(phrase) {
        const command = phrase.toLowerCase();
        if (command.includes('stop demo')) {
            return 'stop';
        }
        if (command.includes('login demo') || command.includes('log in demo')) {
            return 'login';
        }
        if (command.includes('cake demo')) {
            return 'cake';
        }
        if (command.includes('package demo')) {
            return 'package';
        }
        if (command.includes('start demo') || command.includes('run demo') || command.includes('full demo')) {
            return 'full';
        }
        return null;
    }

    quickButtons.forEach((button) => {
        button.addEventListener('click', () => {
            startDemo(button.dataset.scenario, 'button', []);
        });
    });

    customButton.addEventListener('click', () => {
        startDemo('custom', 'button', selectedScriptSteps());
    });

    stopButton.addEventListener('click', () => {
        stopDemo('button');
    });

    if (!SpeechRecognition) {
        voiceToggle.innerHTML = '<i class="fas fa-microphone-slash me-2"></i>Voice Not Supported';
        voiceToggle.disabled = true;
    } else {
        recognition = new SpeechRecognition();
        recognition.lang = 'en-US';
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;

        recognition.addEventListener('start', () => {
            isListening = true;
            voiceToggle.innerHTML = '<i class="fas fa-wave-square me-2"></i>Listening';
            setStatus('Listening for a demo command...', 'listening');
        });

        recognition.addEventListener('end', () => {
            isListening = false;
            voiceToggle.innerHTML = '<i class="fas fa-microphone me-2"></i>Start Listening';
        });

        recognition.addEventListener('error', (event) => {
            isListening = false;
            voiceToggle.innerHTML = '<i class="fas fa-microphone me-2"></i>Start Listening';
            setStatus(`Voice recognition error: ${event.error}`, 'error');
        });

        recognition.addEventListener('result', (event) => {
            const spokenText = event.results[0][0].transcript.trim();
            const command = normalizeVoiceCommand(spokenText);

            if (!command) {
                setStatus(`Command not recognized: "${spokenText}"`, 'error');
                speak('Command not recognized. Say start demo, login demo, cake demo, package demo, or stop demo.');
                return;
            }

            if (command === 'stop') {
                setStatus(`Heard: "${spokenText}"`, 'success');
                stopDemo('voice');
                return;
            }

            setStatus(`Heard: "${spokenText}"`, 'success');
            startDemo(command, 'voice', []);
        });

        voiceToggle.addEventListener('click', () => {
            if (isLaunching || isStopping || lastRunningState) {
                return;
            }

            if (isListening) {
                recognition.stop();
                return;
            }

            recognition.start();
        });
    }

    setControlState(false);
    refreshStatus();
    maybeRunBrowserDemo();
    window.setInterval(refreshStatus, 4000);
})();