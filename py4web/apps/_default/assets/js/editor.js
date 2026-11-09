const EW_TOOLS = [
    ["bold", "italic", "link", "align-left", "align-center", "align-right"],
    [
        "heading",
        "subheading",
        "paragraph",
        "unordered-list",
        "ordered-list",
        // 'table',
        // 'indent',
        // 'unindent',
        // 'line-break'
        // ], [
        // 'image',
        // 'video',
        "preformatted",
    ],
    ["undo", "redo", "remove"],
];

const CONTENT_EDITABLE_SAVE_URL = "/api/content-editable/save";

window.ew_start_editor = (_) => {
    // niet meer on load uitgevoerd maar pas in een block als auth klopt
    // er is natuurlijk ook validatie on save!

    // Keep Shift available for browser shortcuts without activating editable-region highlights.
    // This is the highest safe delay supported by browser timers (roughly 25 days).
    ContentTools.HIGHLIGHT_HOLD_DURATION = 2_147_483_647;

    const editor = ContentTools.EditorApp.get();

    editor.init("*[data-editable]", "data-name");
    editor.toolbox().tools(EW_TOOLS);

    // add .content-edit-activated to body (toggle on start/stop to activate UI changes, see zoetermeer.css)

    editor.addEventListener("start", (_) => {
        document.body.classList.add("content-edit-activated");
    });
    editor.addEventListener("stop", (_) => {
        document.body.classList.remove("content-edit-activated");
    });

    editor.addEventListener("saved", (ev) => {
        // Check that something changed
        const { regions } = ev.detail();
        if (!Object.keys(regions).length) {
            return;
        }

        // Set the editor as busy while we save our changes
        editor.busy(true);

        // Collect the contents of each region into a FormData instance
        const payload = new FormData();
        for (let name in regions) {
            if (regions.hasOwnProperty(name)) {
                payload.append(name, regions[name]);
            }
        }

        const xhr = new XMLHttpRequest();
        xhr.addEventListener("readystatechange", (ev) => {
            // Check if the request is finished
            if (ev.target.readyState === 4) {
                editor.busy(false);

                const saved =
                    ev.target.status === 200 &&
                    ev.target.responseURL === new URL(CONTENT_EDITABLE_SAVE_URL, window.location.origin).href;
                new ContentTools.FlashUI(saved ? "ok" : "no");
            }
        });

        // send the data to be saved
        xhr.open("POST", CONTENT_EDITABLE_SAVE_URL);
        xhr.send(payload);
    });
};

// window.addEventListener('load', _ => );
