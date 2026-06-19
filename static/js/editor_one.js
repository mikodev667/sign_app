(function () {
    "use strict";

    const root = document.querySelector("[data-editor-one]");

    if (!root) {
        return;
    }

    const storageKey = root.dataset.storageKey || "qolqoyu.editorOne.content";
    const useLocalStorage = root.dataset.useLocalStorage !== "0";
    const useStoredMargins = root.dataset.useStoredMargins !== "0";
    const marginsKey = "qolqoyu.editorOne.margins";
    const editor = root.querySelector("[data-editor-content]");
    const paper = root.querySelector("[data-editor-paper]");
    const paperWrap = root.querySelector("[data-editor-paper-wrap]");
    const fileInput = root.querySelector("[data-editor-file]");
    const wordCount = root.querySelector("[data-editor-word-count]");
    const charCount = root.querySelector("[data-editor-char-count]");
    const zoomValue = root.querySelector("[data-editor-zoom-value]");
    const saveStatus = root.querySelector("[data-editor-save-status]");
    const loading = document.querySelector("[data-editor-loading]");
    let initialHtml = "";
    const messages = {
        ready: root.dataset.statusReady || "Saved in this browser",
        saving: root.dataset.statusSaving || "Saving...",
        confirmClear: root.dataset.confirmClear || "Clear the editor content?",
        alertFileType: root.dataset.alertFileType || "Choose a DOCX or PDF file.",
        alertFileRead: root.dataset.alertFileRead || "File could not be read.",
        alertImportPrefix: root.dataset.alertImportPrefix || "Import error",
    };
    let zoom = 100;
    let saveTimer = null;

    function readNumber(value, fallback) {
        const parsed = parseFloat(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    const defaultMargins = {
        top: readNumber(root.dataset.defaultMarginTop, 2),
        bottom: readNumber(root.dataset.defaultMarginBottom, 2),
        left: readNumber(root.dataset.defaultMarginLeft, 2),
        right: readNumber(root.dataset.defaultMarginRight, 2),
    };

    function getModal(name) {
        return document.querySelector(`[data-editor-modal="${name}"]`);
    }

    function openModal(name) {
        const modal = getModal(name);

        if (!modal) {
            return;
        }

        if (typeof modal.showModal === "function") {
            modal.showModal();
        } else {
            modal.setAttribute("open", "open");
        }
    }

    function closeModal(modal) {
        if (!modal) {
            return;
        }

        if (typeof modal.close === "function") {
            modal.close();
        } else {
            modal.removeAttribute("open");
        }
    }

    function setLoading(isLoading) {
        if (loading) {
            loading.hidden = !isLoading;
        }
    }

    function updateStats() {
        const text = editor.innerText || "";
        const trimmed = text.trim();
        const words = trimmed ? trimmed.split(/\s+/).length : 0;

        wordCount.innerText = words;
        charCount.innerText = text.length;
    }

    function markSavedSoon() {
        if (saveStatus) {
            saveStatus.innerText = messages.saving;
        }

        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(function () {
            if (useLocalStorage) {
                localStorage.setItem(storageKey, editor.innerHTML);
            }

            if (saveStatus) {
                saveStatus.innerText = messages.ready;
            }
        }, 250);
    }

    function handleInput() {
        updateStats();
        markSavedSoon();
    }

    function syncRenderedHtmlInput() {
        const input = document.querySelector("[data-editor-rendered-html]");
        const changedInput = document.querySelector("[data-editor-document-changed]");

        if (input) {
            input.value = editor.innerHTML;
        }

        if (changedInput) {
            changedInput.value = editor.innerHTML === initialHtml ? "0" : "1";
        }
    }

    function focusEditor() {
        editor.focus();
    }

    function executeCommand(command, value) {
        focusEditor();
        document.execCommand(command, false, value);
        handleInput();
    }

    function applyFontSize(size) {
        focusEditor();
        document.execCommand("fontSize", false, "7");

        editor.querySelectorAll('font[size="7"]').forEach(function (tag) {
            const span = document.createElement("span");
            span.style.fontSize = `${size}px`;
            span.innerHTML = tag.innerHTML;
            tag.parentNode.replaceChild(span, tag);
        });

        handleInput();
    }

    function applyMargins(margins) {
        paper.style.paddingTop = `${margins.top}cm`;
        paper.style.paddingBottom = `${margins.bottom}cm`;
        paper.style.paddingLeft = `${margins.left}cm`;
        paper.style.paddingRight = `${margins.right}cm`;

        if (useStoredMargins) {
            localStorage.setItem(marginsKey, JSON.stringify(margins));
        }
    }

    function readStoredMargins() {
        if (!useStoredMargins) {
            return Object.assign({}, defaultMargins);
        }

        try {
            return Object.assign({}, defaultMargins, JSON.parse(localStorage.getItem(marginsKey) || "{}"));
        } catch (error) {
            return defaultMargins;
        }
    }

    function applyZoom() {
        paperWrap.style.transform = `scale(${zoom / 100})`;
        paperWrap.style.transformOrigin = "top center";
        zoomValue.innerText = `${zoom}%`;
    }

    function insertHtml(html) {
        focusEditor();
        document.execCommand("insertHTML", false, html);
        handleInput();
    }

    function escapeHtml(value) {
        const div = document.createElement("div");
        div.innerText = value;
        return div.innerHTML;
    }

    function normalizeUrl(url) {
        const trimmed = url.trim();

        if (!trimmed) {
            return "";
        }

        if (/^(https?:|mailto:|tel:)/i.test(trimmed)) {
            return trimmed;
        }

        return `https://${trimmed}`;
    }

    function insertLink() {
        const modal = getModal("link");
        const textInput = modal.querySelector("[data-editor-link-text]");
        const urlInput = modal.querySelector("[data-editor-link-url]");
        const url = normalizeUrl(urlInput.value);

        if (!url) {
            urlInput.focus();
            return;
        }

        const text = textInput.value.trim() || url;
        insertHtml(`<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(text)}</a>`);
        textInput.value = "";
        urlInput.value = "";
        closeModal(modal);
    }

    function insertTable() {
        const modal = getModal("table");
        const rows = Math.max(1, Math.min(20, parseInt(modal.querySelector("[data-editor-table-rows]").value, 10) || 1));
        const cols = Math.max(1, Math.min(12, parseInt(modal.querySelector("[data-editor-table-cols]").value, 10) || 1));
        const width = modal.querySelector("[data-editor-table-width]").value.trim() || "100%";
        const padding = Math.max(0, Math.min(40, parseInt(modal.querySelector("[data-editor-table-padding]").value, 10) || 0));
        let html = `<table style="width:${escapeHtml(width)}; border-collapse:collapse; margin:1rem 0;">`;

        html += "<tbody>";
        for (let row = 0; row < rows; row += 1) {
            html += "<tr>";
            for (let col = 0; col < cols; col += 1) {
                html += `<td style="border:1px solid #d1d5db; padding:${padding}px; min-width:60px;"><br></td>`;
            }
            html += "</tr>";
        }
        html += "</tbody></table><p><br></p>";

        insertHtml(html);
        closeModal(modal);
    }

    function applyMarginsFromModal() {
        const modal = getModal("margins");
        const margins = Object.assign({}, defaultMargins);

        modal.querySelectorAll("[data-editor-margin]").forEach(function (input) {
            margins[input.dataset.editorMargin] = Math.max(0, Math.min(8, parseFloat(input.value) || 0));
        });

        applyMargins(margins);
        closeModal(modal);
    }

    function fillMarginsModal() {
        const margins = readStoredMargins();
        const modal = getModal("margins");

        modal.querySelectorAll("[data-editor-margin]").forEach(function (input) {
            input.value = margins[input.dataset.editorMargin];
        });
    }

    function readFileAsArrayBuffer(file) {
        return new Promise(function (resolve, reject) {
            const reader = new FileReader();
            reader.onload = function () {
                resolve(reader.result);
            };
            reader.onerror = function () {
                reject(new Error(messages.alertFileRead));
            };
            reader.readAsArrayBuffer(file);
        });
    }

    async function processDocx(arrayBuffer) {
        if (typeof window.mammoth === "undefined") {
            throw new Error("Mammoth library is not loaded");
        }

        const result = await window.mammoth.convertToHtml({ arrayBuffer: arrayBuffer });
        return result.value;
    }

    async function processPdf(arrayBuffer) {
        if (typeof window.pdfjsLib === "undefined") {
            throw new Error("PDF.js library is not loaded");
        }

        window.pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

        const pdf = await window.pdfjsLib.getDocument({ data: new Uint8Array(arrayBuffer) }).promise;
        let html = "";

        for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
            const page = await pdf.getPage(pageNumber);
            const textContent = await page.getTextContent();
            const lines = {};

            textContent.items.forEach(function (item) {
                const y = Math.round(item.transform[5]);
                if (!lines[y]) {
                    lines[y] = [];
                }
                lines[y].push(item.str);
            });

            const pageText = Object.keys(lines)
                .map(Number)
                .sort(function (a, b) {
                    return b - a;
                })
                .map(function (y) {
                    return lines[y].join(" ");
                })
                .join("<br>");

            html += `<section style="margin-bottom:20px;">${pageText}</section>`;

            if (pageNumber < pdf.numPages) {
                html += '<hr style="border:0; border-top:1px dashed #d1d5db; margin:2rem 0;">';
            }
        }

        return html;
    }

    async function handleFileUpload(event) {
        const file = event.target.files && event.target.files[0];

        if (!file) {
            return;
        }

        const extension = (file.name.split(".").pop() || "").toLowerCase();

        if (!["docx", "pdf", "doc"].includes(extension)) {
            window.alert(messages.alertFileType);
            return;
        }

        setLoading(true);

        try {
            const arrayBuffer = await readFileAsArrayBuffer(file);
            let html = "";

            if (extension === "pdf") {
                html = await processPdf(arrayBuffer);
            } else {
                html = await processDocx(arrayBuffer);
            }

            editor.innerHTML = html || "<p><br></p>";
            handleInput();
        } catch (error) {
            window.alert(`${messages.alertImportPrefix}: ${error.message}`);
        } finally {
            setLoading(false);
            fileInput.value = "";
        }
    }

    function handlePaste(event) {
        const html = event.clipboardData.getData("text/html");

        if (!html || (!html.includes("mso-") && !html.includes("office:office"))) {
            return;
        }

        event.preventDefault();

        const cleaned = html
            .replace(/<o:p>[\s\S]*?<\/o:p>/gi, "")
            .replace(/class="Mso[^"]*"/gi, "")
            .replace(/style="[^"]*mso-[^"]*"/gi, "");

        insertHtml(cleaned);
    }

    function downloadHtml() {
        const html = [
            "<!doctype html>",
            '<html lang="ru">',
            "<head>",
            '<meta charset="utf-8">',
            "<title>Editor 1 document</title>",
            "</head>",
            "<body>",
            editor.innerHTML,
            "</body>",
            "</html>",
        ].join("\n");
        const blob = new Blob([html], { type: "text/html;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");

        link.href = url;
        link.download = "editor-1-document.html";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    }

    root.querySelectorAll("[data-editor-command]").forEach(function (control) {
        const eventName = control.tagName === "SELECT" || control.type === "color" ? "change" : "click";

        control.addEventListener(eventName, function () {
            executeCommand(control.dataset.editorCommand, control.value || null);
        });
    });

    root.querySelectorAll("[data-editor-color-picker]").forEach(function (input) {
        const wrapper = input.closest(".editor-one__color");

        if (wrapper) {
            wrapper.style.setProperty("--editor-color", input.value);
        }

        input.addEventListener("change", function () {
            if (wrapper) {
                wrapper.style.setProperty("--editor-color", input.value);
            }

            executeCommand(input.dataset.editorColorPicker, input.value);
        });
    });

    root.querySelectorAll("[data-editor-color-apply]").forEach(function (button) {
        button.addEventListener("click", function () {
            const command = button.dataset.editorColorApply;
            const wrapper = button.closest(".editor-one__color");
            const picker = wrapper ? wrapper.querySelector("[data-editor-color-picker]") : null;

            executeCommand(command, picker ? picker.value : null);
        });
    });

    root.querySelector("[data-editor-font-size]").addEventListener("change", function (event) {
        applyFontSize(event.target.value);
    });

    root.querySelectorAll("[data-editor-action]").forEach(function (button) {
        button.addEventListener("click", function () {
            const action = button.dataset.editorAction;

            if (action === "upload") {
                fileInput.click();
                return;
            }

            if (action === "clear") {
                if (window.confirm(messages.confirmClear)) {
                    editor.innerHTML = "<p><br></p>";
                    handleInput();
                }
                return;
            }

            if (action === "link") {
                const selection = window.getSelection();
                const modal = getModal("link");
                modal.querySelector("[data-editor-link-text]").value = selection ? selection.toString() : "";
            }

            if (action === "margins") {
                fillMarginsModal();
            }

            openModal(action);
        });
    });

    root.querySelectorAll("[data-editor-zoom]").forEach(function (button) {
        button.addEventListener("click", function () {
            zoom += parseInt(button.dataset.editorZoom, 10);
            zoom = Math.max(50, Math.min(150, zoom));
            applyZoom();
        });
    });

    document.querySelectorAll("[data-editor-modal-close]").forEach(function (button) {
        button.addEventListener("click", function () {
            closeModal(button.closest("dialog"));
        });
    });

    document.querySelector("[data-editor-link-insert]").addEventListener("click", insertLink);
    document.querySelector("[data-editor-table-insert]").addEventListener("click", insertTable);
    document.querySelector("[data-editor-margins-apply]").addEventListener("click", applyMarginsFromModal);
    root.querySelectorAll("[data-editor-download]").forEach(function (button) {
        button.addEventListener("click", downloadHtml);
    });
    fileInput.addEventListener("change", handleFileUpload);
    editor.addEventListener("input", handleInput);
    editor.addEventListener("blur", handleInput);
    editor.addEventListener("paste", handlePaste);
    editor.addEventListener("keydown", function (event) {
        if (event.key === "Tab") {
            event.preventDefault();
            insertHtml("&nbsp;&nbsp;&nbsp;&nbsp;");
        }
    });

    document.querySelectorAll("[data-editor-save-form]").forEach(function (form) {
        form.addEventListener("submit", function () {
            syncRenderedHtmlInput();

            if (useLocalStorage) {
                localStorage.setItem(storageKey, editor.innerHTML);
            }
        });
    });

    initialHtml = editor.innerHTML;

    const storedContent = useLocalStorage ? localStorage.getItem(storageKey) : "";
    if (storedContent) {
        editor.innerHTML = storedContent;
    }

    applyMargins(readStoredMargins());
    updateStats();
    applyZoom();
}());
