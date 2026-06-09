class NCALayerClient {
    constructor() {
        this.websocket = null;
        this.requestId = 1;
        this.callbacks = {};
    }

    connect() {
        return new Promise((resolve, reject) => {
            this.websocket = new WebSocket("wss://127.0.0.1:13579/");

            this.websocket.onopen = () => {
                console.log("NCALayer connected");
                resolve();
            };

            this.websocket.onerror = (event) => {
                console.error("NCALayer connection error:", event);
                reject(new Error("Cannot connect to NCALayer. Make sure NCALayer is running."));
            };

            this.websocket.onclose = () => {
                console.warn("NCALayer connection closed.");

                Object.keys(this.callbacks).forEach((requestId) => {
                    this.callbacks[requestId].reject(
                        new Error("NCALayer connection was closed.")
                    );
                    delete this.callbacks[requestId];
                });
            };

            this.websocket.onmessage = (event) => {
                console.log("NCALayer raw response:", event.data);

                let response;

                try {
                    response = JSON.parse(event.data);
                } catch (error) {
                    console.error("Cannot parse NCALayer response:", event.data);
                    return;
                }

                console.log("NCALayer parsed response:", response);

                /*
                    NCALayer sometimes sends service response first:
                    {"result":{"version":"1.4"}}

                    This is not the signing result.
                    We must ignore it and wait for the real CMS response.
                */
                if (
                    response.result &&
                    response.result.version &&
                    !response.status &&
                    !response.body
                ) {
                    console.log("NCALayer version response ignored:", response.result.version);
                    return;
                }

                const requestId = String(response.requestId || "");
                const pendingIds = Object.keys(this.callbacks);

                if (requestId && this.callbacks[requestId]) {
                    this.callbacks[requestId].resolve(response);
                    delete this.callbacks[requestId];
                    return;
                }

                if (pendingIds.length > 0) {
                    const lastRequestId = pendingIds[pendingIds.length - 1];
                    this.callbacks[lastRequestId].resolve(response);
                    delete this.callbacks[lastRequestId];
                    return;
                }

                console.warn("NCALayer response received but no callback found:", response);
            };
        });
    }

    send(module, method, args) {
        return new Promise((resolve, reject) => {
            if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
                reject(new Error("NCALayer websocket is not connected."));
                return;
            }

            const requestId = String(this.requestId++);

            const payload = {
                module: module,
                method: method,
                args: args,
                requestId: requestId
            };

            console.log("NCALayer request:", payload);

            const timeoutId = setTimeout(() => {
                if (this.callbacks[requestId]) {
                    delete this.callbacks[requestId];
                    reject(new Error("NCALayer did not respond after signing."));
                }
            }, 120000);

            this.callbacks[requestId] = {
                resolve: (response) => {
                    clearTimeout(timeoutId);

                    if (
                        response.status === true ||
                        response.code === "200" ||
                        response.body ||
                        response.responseObject
                    ) {
                        resolve(response);
                    } else {
                        reject(response);
                    }
                },
                reject: (error) => {
                    clearTimeout(timeoutId);
                    reject(error);
                }
            };

            this.websocket.send(JSON.stringify(payload));
        });
    }

    signCmsBase64(base64Data) {
        const args = {
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
        };

        return this.send(
            "kz.gov.pki.knca.basics",
            "sign",
            args
        );
    }
}

function getCsrfToken() {
    const input = document.querySelector("input[name='csrfmiddlewaretoken']");
    return input ? input.value : "";
}

function extractCmsSignature(response) {
    console.log("Trying to extract CMS from response:", response);

    if (!response) {
        return "";
    }

    if (typeof response === "string") {
        return response;
    }

    /*
        Real NCALayer response in your case:

        {
            "body": {
                "result": [
                    "-----BEGIN CMS-----..."
                ]
            },
            "status": true
        }
    */
    if (
        response.body &&
        Array.isArray(response.body.result) &&
        response.body.result.length > 0
    ) {
        return response.body.result[0];
    }

    if (
        response.body &&
        typeof response.body.result === "string"
    ) {
        return response.body.result;
    }

    if (typeof response.responseObject === "string") {
        return response.responseObject;
    }

    if (response.responseObject && typeof response.responseObject === "object") {
        if (response.responseObject.cms) {
            return response.responseObject.cms;
        }

        if (response.responseObject.result) {
            return response.responseObject.result;
        }

        if (response.responseObject.signature) {
            return response.responseObject.signature;
        }

        if (response.responseObject.data) {
            return response.responseObject.data;
        }
    }

    if (typeof response.result === "string") {
        return response.result;
    }

    if (typeof response.body === "string") {
        return response.body;
    }

    if (typeof response.cms === "string") {
        return response.cms;
    }

    if (typeof response.signature === "string") {
        return response.signature;
    }

    return "";
}

async function signDocumentWithEcp(payloadUrl, completeUrl) {
    const statusBox = document.getElementById("ecp-status");
    const button = document.getElementById("ecp-sign-button");

    try {
        button.disabled = true;
        statusBox.innerText = "Подготавливаем данные для подписания...";

        const payloadResponse = await fetch(payloadUrl);

        if (!payloadResponse.ok) {
            throw new Error("Backend returned error while preparing signing payload.");
        }

        const payloadData = await payloadResponse.json();

        console.log("Backend payload response:", payloadData);

        if (!payloadData.ok) {
            throw new Error(payloadData.error || "Cannot prepare signing payload.");
        }

        statusBox.innerText = "Подключение к NCALayer...";

        const client = new NCALayerClient();
        await client.connect();

        statusBox.innerText = "Выберите ключ ЭЦП и подпишите документ...";

        const signedResponse = await client.signCmsBase64(
            payloadData.payload_base64
        );

        console.log("Signed response from NCALayer:", signedResponse);

        const cmsSignature = extractCmsSignature(signedResponse);

        console.log("Extracted CMS signature:", cmsSignature ? "CMS exists" : "CMS empty");

        if (!cmsSignature) {
            throw new Error("NCALayer returned empty signature. Check console response format.");
        }

        statusBox.innerText = "Сохраняем подпись...";

        const completeResponse = await fetch(completeUrl, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCsrfToken()
            },
            body: JSON.stringify({
                cms_signature: cmsSignature,
                certificate_subject: "",
                certificate_serial_number: "",
                ncalayer_response: signedResponse
            })
        });

        if (!completeResponse.ok) {
            let errorText = "";

            try {
                errorText = await completeResponse.text();
            } catch (error) {
                errorText = "";
            }

            console.error("Backend complete error response:", errorText);

            throw new Error("Backend returned error while saving ECP signature.");
        }

        const completeData = await completeResponse.json();

        console.log("Backend complete response:", completeData);

        if (!completeData.ok) {
            throw new Error(completeData.error || "Cannot complete signing.");
        }

        statusBox.innerText = "Документ успешно подписан через ЭЦП.";

        if (completeData.redirect_url) {
            window.location.href = completeData.redirect_url;
        } else {
            window.location.reload();
        }

    } catch (error) {
        console.error("ECP signing error:", error);

        if (typeof error === "object" && error !== null) {
            statusBox.innerText =
                error.message ||
                error.description ||
                error.error ||
                JSON.stringify(error);
        } else {
            statusBox.innerText = String(error);
        }

        button.disabled = false;
    }
}