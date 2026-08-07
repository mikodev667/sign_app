(function () {
    "use strict";

    const ruHundreds = {
        1: "сто",
        2: "двести",
        3: "триста",
        4: "четыреста",
        5: "пятьсот",
        6: "шестьсот",
        7: "семьсот",
        8: "восемьсот",
        9: "девятьсот",
    };
    const ruTens = {
        2: "двадцать",
        3: "тридцать",
        4: "сорок",
        5: "пятьдесят",
        6: "шестьдесят",
        7: "семьдесят",
        8: "восемьдесят",
        9: "девяносто",
    };
    const ruTeens = {
        10: "десять",
        11: "одиннадцать",
        12: "двенадцать",
        13: "тринадцать",
        14: "четырнадцать",
        15: "пятнадцать",
        16: "шестнадцать",
        17: "семнадцать",
        18: "восемнадцать",
        19: "девятнадцать",
    };
    const ruUnitsMasculine = {
        1: "один",
        2: "два",
        3: "три",
        4: "четыре",
        5: "пять",
        6: "шесть",
        7: "семь",
        8: "восемь",
        9: "девять",
    };
    const ruUnitsFeminine = {
        ...ruUnitsMasculine,
        1: "одна",
        2: "две",
    };
    const ruScales = [
        null,
        ["тысяча", "тысячи", "тысяч"],
        ["миллион", "миллиона", "миллионов"],
        ["миллиард", "миллиарда", "миллиардов"],
        ["триллион", "триллиона", "триллионов"],
    ];

    const kkUnits = {
        1: "бір",
        2: "екі",
        3: "үш",
        4: "төрт",
        5: "бес",
        6: "алты",
        7: "жеті",
        8: "сегіз",
        9: "тоғыз",
    };
    const kkTens = {
        1: "он",
        2: "жиырма",
        3: "отыз",
        4: "қырық",
        5: "елу",
        6: "алпыс",
        7: "жетпіс",
        8: "сексен",
        9: "тоқсан",
    };
    const kkScales = ["", "мың", "миллион", "миллиард", "триллион"];

    function parseAmount(rawValue) {
        let normalized = String(rawValue || "")
            .trim()
            .replace(/\u00a0/g, "")
            .replace(/\s/g, "")
            .replace(/_/g, "");

        if (!normalized) {
            return null;
        }

        if (normalized.includes(",") && !normalized.includes(".")) {
            normalized = normalized.replace(",", ".");
        }

        if (!/^\d+(\.\d+)?$/.test(normalized)) {
            return null;
        }

        const amount = Number(normalized);
        if (!Number.isSafeInteger(amount) || amount < 0) {
            return null;
        }

        return amount;
    }

    function formatAmount(amount) {
        return String(amount).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    }

    function pluralRu(number, forms) {
        const lastTwo = number % 100;
        const last = number % 10;

        if (lastTwo >= 11 && lastTwo <= 14) {
            return forms[2];
        }
        if (last === 1) {
            return forms[0];
        }
        if (last >= 2 && last <= 4) {
            return forms[1];
        }
        return forms[2];
    }

    function tripletRu(number, gender) {
        const parts = [];
        const hundreds = Math.floor(number / 100);
        const rest = number % 100;

        if (hundreds) {
            parts.push(ruHundreds[hundreds]);
        }

        if (rest >= 10 && rest <= 19) {
            parts.push(ruTeens[rest]);
            return parts;
        }

        const tens = Math.floor(rest / 10);
        const units = rest % 10;

        if (tens) {
            parts.push(ruTens[tens]);
        }

        if (units) {
            parts.push((gender === "feminine" ? ruUnitsFeminine : ruUnitsMasculine)[units]);
        }

        return parts;
    }

    function wordsRu(amount) {
        if (amount === 0) {
            return "ноль тенге";
        }

        const parts = [];
        let value = amount;
        let groupIndex = 0;

        while (value) {
            const groupValue = value % 1000;

            if (groupValue) {
                const gender = groupIndex === 1 ? "feminine" : "masculine";
                const groupParts = tripletRu(groupValue, gender);
                const scaleForms = ruScales[groupIndex];

                if (scaleForms) {
                    groupParts.push(pluralRu(groupValue, scaleForms));
                }

                parts.unshift(groupParts.join(" "));
            }

            value = Math.floor(value / 1000);
            groupIndex += 1;
        }

        parts.push("тенге");
        return parts.join(" ");
    }

    function tripletKk(number) {
        const parts = [];
        const hundreds = Math.floor(number / 100);
        const rest = number % 100;
        const tens = Math.floor(rest / 10);
        const units = rest % 10;

        if (hundreds) {
            if (hundreds > 1) {
                parts.push(kkUnits[hundreds]);
            }
            parts.push("жүз");
        }

        if (tens) {
            parts.push(kkTens[tens]);
        }

        if (units) {
            parts.push(kkUnits[units]);
        }

        return parts;
    }

    function wordsKk(amount) {
        if (amount === 0) {
            return "нөл теңге";
        }

        const parts = [];
        let value = amount;
        let groupIndex = 0;

        while (value) {
            const groupValue = value % 1000;

            if (groupValue) {
                const groupParts = tripletKk(groupValue);
                const scale = kkScales[groupIndex] || "";

                if (scale) {
                    groupParts.push(scale);
                }

                parts.unshift(groupParts.join(" "));
            }

            value = Math.floor(value / 1000);
            groupIndex += 1;
        }

        parts.push("теңге");
        return parts.join(" ");
    }

    function updatePreview(input) {
        const field = input.closest(".admission-public-field");
        const preview = field ? field.querySelector("[data-money-preview]") : null;
        const ruTarget = preview ? preview.querySelector("[data-money-preview-ru]") : null;
        const kkTarget = preview ? preview.querySelector("[data-money-preview-kk]") : null;

        if (!preview || !ruTarget || !kkTarget) {
            return;
        }

        const amount = parseAmount(input.value);
        if (amount === null) {
            preview.hidden = true;
            ruTarget.textContent = "";
            kkTarget.textContent = "";
            return;
        }

        const formatted = formatAmount(amount);
        ruTarget.textContent = `${formatted} (${wordsRu(amount)})`;
        kkTarget.textContent = `${formatted} (${wordsKk(amount)})`;
        preview.hidden = false;
    }

    document.querySelectorAll("[data-money-preview-input]").forEach((input) => {
        input.addEventListener("input", () => updatePreview(input));
        updatePreview(input);
    });
}());
