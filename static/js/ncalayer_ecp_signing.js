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
                resolve();
            };

            this.websocket.onerror = () => {
                reject(new Error("Cannot connect to NCALayer."));
            };

            this.websocket.onclose = () => {
                console.warn("NCALayer connection closed.");
            };

            this.websocket.onmessage = (event) => {
                const response = JSON.parse(event.data);
                const requestId = response.requestId;

                if (requestId && this.callbacks[requestId]) {
                    this.callbacks[requestId](response);
                    delete this.callbacks[requestId];
                }
            };
        });
    }

    send(module, method, args) {
        return new Promise((resolve, reject) => {
            const requestId = String(this.requestId++);

            const payload = {
                module: module,
                method: method,
                args: args,
                requestId: requestId
            };

            this.callbacks[requestId] = (response) => {
                if (response.status === true || response.code === "200") {
                    resolve(response);
                } else {
                    reject(response);
                }
            };

            this.websocket.send(JSON.stringify(payload));
        });
    }

    signCmsBase64(base64Data, signerIin) {
        const allowedStorages = ["PKCS12"];

        const format = "cms";

        const signingParams = {
            decode: true,
            encapsulate: true,
            digested: false,
            tsaProfile: {}
        };

        const signerParams = {
            iin: signerIin || "",
            extKeyUsageOids: ["1.3.6.1.5.5.7.3.4"]
        };

        const locale = "ru";

        return this.send(
            "kz.gov.pki.knca.basics",
            "sign",
            [
                allowedStorages,
                format,
                base64Data,
                signingParams,
                signerParams,
                locale
            ]
        );
    }
}

function getCsrfToken() {
    const input = document.querySelector("input[name='csrfmiddlewaretoken']");
    return input ? input.value : "";
}

async function signDocumentWithEcp(payloadUrl, completeUrl) {
    const statusBox = document.getElementById("ecp-status");
    const button = document.getElementById("ecp-sign-button");

    try {
        button.disabled = true;
        statusBox.innerText = "Подключение к NCALayer...";

        const payloadResponse = await fetch(payloadUrl);
        const payloadData = await payloadResponse.json();

        if (!payloadData.ok) {
            throw new Error(payloadData.error || "Cannot prepare signing payload.");
        }

        const client = new NCALayerClient();
        await client.connect();

        statusBox.innerText = "Выберите ключ ЭЦП и подпишите документ...";

        const signedResponse = await client.signCmsBase64(
            payloadData.payload_base64,
            payloadData.signer_iin
        );

        const cmsSignature =
            signedResponse.responseObject ||
            signedResponse.body ||
            signedResponse.result ||
            "";

        if (!cmsSignature) {
            throw new Error("NCALayer returned empty signature.");
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
                certificate_serial_number: ""
            })
        });

        const completeData = await completeResponse.json();

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
        console.error(error);
        statusBox.innerText = error.message || "Ошибка подписания через ЭЦП.";
        button.disabled = false;
    }
}