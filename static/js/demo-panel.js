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
    let isLaunching = false;
    let isStopping = false;
    let isListening = false;
    let recognition = null;
    let lastRunningState = false;

    function setStatus(message, state) {
        statusNode.textContent = message;
        statusNode.dataset.state = state;
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
    window.setInterval(refreshStatus, 4000);
})();