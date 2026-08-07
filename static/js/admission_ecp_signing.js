(function () {
    class AdmissionNCALayerClient {
        constructor(messages) {
            this.websocket = null;
            this.requestId = 1;
            this.callbacks = {};
            this.messages = messages || {};
        }

        connect() {
            return new Promise((resolve, reject) => {
                this.websocket = new WebSocket("wss://127.0.0.1:13579/");

                this.websocket.onopen = () => resolve();
                this.websocket.onerror = () => reject(new Error(this.messages.cannotConnect || "Cannot connect to NCALayer."));
                this.websocket.onclose = () => {
                    Object.keys(this.callbacks).forEach((requestId) => {
                        this.callbacks[requestId].reject(new Error(this.messages.connectionClosed || "NCALayer connection was closed."));
                        delete this.callbacks[requestId];
                    });
                };
                this.websocket.onmessage = (event) => this.handleMessage(event);
            });
        }

        handleMessage(event) {
            let response = null;

            try {
                response = JSON.parse(event.data);
            } catch (error) {
                return;
            }

            if (response.result && response.result.version && !response.status && !response.body) {
                return;
            }

            const requestId = String(response.requestId || "");

            if (requestId && this.callbacks[requestId]) {
                this.callbacks[requestId].resolve(response);
                delete this.callbacks[requestId];
                return;
            }

            const pendingIds = Object.keys(this.callbacks);
            if (pendingIds.length > 0) {
                const lastRequestId = pendingIds[pendingIds.length - 1];
                this.callbacks[lastRequestId].resolve(response);
                delete this.callbacks[lastRequestId];
            }
        }

        send(module, method, args) {
            return new Promise((resolve, reject) => {
                if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
                    reject(new Error(this.messages.websocketNotConnected || "NCALayer websocket is not connected."));
                    return;
                }

                const requestId = String(this.requestId++);
                const timeoutId = window.setTimeout(() => {
                    if (this.callbacks[requestId]) {
                        delete this.callbacks[requestId];
                        reject(new Error(this.messages.timeout || "NCALayer did not respond after signing."));
                    }
                }, 120000);

                this.callbacks[requestId] = {
                    resolve: (response) => {
                        window.clearTimeout(timeoutId);
                        if (response.status === true || response.code === "200" || response.body || response.responseObject) {
                            resolve(response);
                        } else {
                            reject(response);
                        }
                    },
                    reject: (error) => {
                        window.clearTimeout(timeoutId);
                        reject(error);
                    }
                };

                this.websocket.send(JSON.stringify({
                    module: module,
                    method: method,
                    args: args,
                    requestId: requestId
                }));
            });
        }

        signCmsBase64(base64Data) {
            return this.send("kz.gov.pki.knca.basics", "sign", {
                allowedStorages: ["PKCS12"],
                format: "cms",
                data: base64Data,
                signingParams: {
                    decode: true,
                    encapsulate: true,
                    digested: false,
                    tsaProfile: {}
                },
                signerParams: {
                    extKeyUsageOids: [],
                    iin: "",
                    bin: "",
                    serialNumber: "",
                    chain: null
                },
                locale: "ru"
            });
        }
    }

    function csrfToken() {
        const input = document.querySelector("input[name='csrfmiddlewaretoken']");
        return input ? input.value : "";
    }

    function cmsFromResponse(response) {
        if (!response) {
            return "";
        }

        if (typeof response === "string") {
            return response;
        }

        if (response.body && Array.isArray(response.body.result) && response.body.result.length > 0) {
            return response.body.result[0];
        }

        if (response.body && typeof response.body.result === "string") {
            return response.body.result;
        }

        if (typeof response.responseObject === "string") {
            return response.responseObject;
        }

        if (response.responseObject && typeof response.responseObject === "object") {
            return (
                response.responseObject.cms ||
                response.responseObject.result ||
                response.responseObject.signature ||
                response.responseObject.data ||
                ""
            );
        }

        return response.result || response.body || response.cms || response.signature || "";
    }

    function statusBoxFor(button) {
        if (button && button.dataset.statusTarget) {
            return document.getElementById(button.dataset.statusTarget);
        }

        return document.getElementById("admission-ecp-status");
    }

    function setStatus(button, text, isError) {
        const statusBox = statusBoxFor(button);
        if (!statusBox) {
            return;
        }

        statusBox.textContent = text || "";
        statusBox.classList.toggle("admission-public-sign-status--error", Boolean(isError));
    }

    async function sign(button) {
        const payloadUrl = button.dataset.payloadUrl;
        const completeUrl = button.dataset.completeUrl;
        const ncalayerMessages = {
            cannotConnect: button.dataset.errorCannotConnect,
            connectionClosed: button.dataset.errorConnectionClosed,
            websocketNotConnected: button.dataset.errorWebsocketNotConnected,
            timeout: button.dataset.errorNcalayerTimeout
        };

        try {
            button.disabled = true;
            setStatus(button, button.dataset.statusPreparing);

            const payloadResponse = await fetch(payloadUrl, { credentials: "same-origin" });
            const payloadData = await payloadResponse.json();

            if (!payloadResponse.ok || !payloadData.ok) {
                throw new Error(payloadData.error || button.dataset.errorCannotPrepare || "Cannot prepare signing payload.");
            }

            setStatus(button, button.dataset.statusConnecting);
            const client = new AdmissionNCALayerClient(ncalayerMessages);
            await client.connect();

            setStatus(button, button.dataset.statusChoosing);
            const signedResponse = await client.signCmsBase64(payloadData.payload_base64);
            const cmsSignature = cmsFromResponse(signedResponse);

            if (!cmsSignature) {
                throw new Error(button.dataset.errorEmptyCms || "NCALayer returned an empty CMS signature.");
            }

            setStatus(button, button.dataset.statusSaving);
            const completeResponse = await fetch(completeUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken()
                },
                body: JSON.stringify({
                    cms_signature: cmsSignature,
                    certificate_subject: "",
                    certificate_serial_number: "",
                    ncalayer_response: signedResponse
                })
            });
            const completeData = await completeResponse.json();

            if (!completeResponse.ok || !completeData.ok) {
                throw new Error(completeData.error || button.dataset.errorCannotComplete || "Cannot complete signing.");
            }

            setStatus(button, button.dataset.statusSigned);
            window.location.href = completeData.redirect_url || window.location.href;
        } catch (error) {
            setStatus(button, error.message || String(error), true);
            button.disabled = false;
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        const buttons = Array.from(document.querySelectorAll("[data-admission-ecp-sign]"));
        const legacyButton = document.getElementById("admission-ecp-sign-button");

        if (legacyButton && !buttons.includes(legacyButton)) {
            buttons.push(legacyButton);
        }

        buttons.forEach((button) => {
            button.addEventListener("click", () => sign(button));
        });
    });
})();
