type ItemType = "good" | "bonus" | "shield" | "heart" | "hazard";

interface FallingItem {
    element: HTMLDivElement;
    size: number;
    x: number;
    y: number;
    speed: number;
    type: ItemType;
}

let initialized_board: HTMLElement | null = null;

function initialize_error_game(): void {
    const $board = document.querySelector<HTMLElement>(".error-game .game-board");
    const $catcher = document.querySelector<HTMLElement>(".error-game .catcher");
    const $start_button = document.querySelector<HTMLButtonElement>(".error-game .start-button");
    const $message = document.querySelector<HTMLElement>(".error-game .board-message");
    if (!$board || !$catcher || !$start_button || !$message || initialized_board === $board) {
        return;
    }
    initialized_board = $board;
    window.okl_page.signal.addEventListener(
        "abort",
        () => {
            initialized_board = null;
        },
        { once: true },
    );
    initialize_game($board, $catcher, $start_button, $message);
}

function initialize_game(
    $board: HTMLElement,
    $catcher: HTMLElement,
    $start_button: HTMLButtonElement,
    $message: HTMLElement,
): void {
    const good_items = [
        { emoji: "💡", label: "goed idee" },
        { emoji: "🔬", label: "ontdekking" },
        { emoji: "🎨", label: "creativiteit" },
        { emoji: "🌍", label: "nieuwe wereld" },
        { emoji: "🧩", label: "oplossing" },
        { emoji: "✨", label: "aha-moment" },
        { emoji: "🎵", label: "inspiratie" },
        { emoji: "🚀", label: "doorbraak" },
    ];
    const hazard_items = [
        { emoji: "☁️", label: "grijze wolk" },
        { emoji: "🐻", label: "beer op de weg" },
    ];
    const $score_output = document.querySelector<HTMLElement>(".error-game .game-score")!;
    const $level_output = document.querySelector<HTMLElement>(".error-game .game-level")!;
    const $combo_output = document.querySelector<HTMLElement>(".error-game .game-combo")!;
    const $lives_output = document.querySelector<HTMLElement>(".error-game .game-lives")!;
    const $start_label = document.querySelector<HTMLElement>(".error-game .game-start-label")!;
    const $live_output = document.querySelector<HTMLElement>(".error-game .game-live")!;
    const $high_score_output = document.querySelector<HTMLElement>(".error-game .high-score")!;
    const $play_status_output = document.querySelector<HTMLElement>(".error-game .play-status")!;
    const $feedback_output = document.querySelector<HTMLElement>(".error-game .catch-feedback")!;
    const $level_toast = document.querySelector<HTMLElement>(".error-game .level-toast")!;
    const $message_emoji = document.querySelector<HTMLElement>(".error-game .message-emoji")!;
    const $message_title = document.querySelector<HTMLElement>(".error-game .message-title")!;
    const $message_copy = document.querySelector<HTMLElement>(".error-game .board-message__copy")!;
    const $catcher_face = document.querySelector<HTMLElement>(".error-game .catcher__face")!;
    const $sound_icon = document.querySelector<HTMLElement>(".error-game .sound-icon")!;
    const $sound_toggle = document.querySelector<HTMLButtonElement>(".error-game .sound-toggle")!;
    const $sound_state = $sound_toggle.querySelector<HTMLElement>(".sound-toggle__state")!;
    const $$move_buttons = document.querySelectorAll<HTMLButtonElement>(".error-game .move-button");

    let items: FallingItem[] = [];
    let score = 0;
    let level = 1;
    let lives = 3;
    let streak = 0;
    let high_score = read_high_score();
    let sound_enabled = read_sound_preference();
    let audio_context: AudioContext | null = null;
    let audio_output: GainNode | null = null;
    let shield_active = false;
    let catcher_position = 50;
    let running = false;
    let movement = 0;
    let last_frame = 0;
    let last_spawn = 0;
    let animation_frame = 0;
    let feedback_timer = 0;
    let level_toast_timer = 0;
    let spawns_since_damage = 0;
    let board_width = 0;
    let board_height = 0;
    let catcher_width = 0;
    let catcher_height = 0;
    let catcher_top = 0;
    const pressed_directions = new Set<"left" | "right">();

    function read_high_score(): number {
        try {
            return Number.parseInt(window.localStorage.getItem("leervonk-high-score") || "0", 10) || 0;
        } catch {
            return 0;
        }
    }

    function save_high_score(): void {
        if (score <= high_score) {
            return;
        }
        high_score = score;
        try {
            window.localStorage.setItem("leervonk-high-score", String(high_score));
        } catch {
            // The game remains fully playable when browser storage is unavailable.
        }
    }

    function read_sound_preference(): boolean {
        try {
            return window.sessionStorage.getItem("leervonk-sound-enabled") === "true";
        } catch {
            return false;
        }
    }

    function update_sound_toggle(): void {
        $sound_icon.textContent = sound_enabled ? "🔊" : "🔇";
        $sound_icon.classList.toggle("is-muted", !sound_enabled);
        $sound_state.textContent = sound_enabled ? "Aan" : "Uit";
        $sound_toggle.setAttribute("aria-checked", String(sound_enabled));
        if (audio_output) {
            audio_output.gain.value = sound_enabled ? 1 : 0;
        }
    }

    function enable_audio(): Promise<void> {
        if (!sound_enabled || typeof AudioContext === "undefined") {
            return Promise.resolve();
        }
        try {
            if (!audio_context) {
                audio_context = new AudioContext();
                audio_output = audio_context.createGain();
                audio_output.connect(audio_context.destination);
            }
            if (audio_context.state === "suspended") {
                return audio_context.resume().catch(() => {});
            }
        } catch {
            // Sound is optional when the browser does not allow audio.
        }
        return Promise.resolve();
    }

    type SoundNote = {
        frequency: number;
        end_frequency?: number;
        delay?: number;
        duration: number;
        volume: number;
        wave?: OscillatorType | "noise";
        detune?: number;
    };

    // Rising major pentatonic, so a streak of good catches climbs audibly.
    const streak_steps = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21, 24];
    let noise_buffer: AudioBuffer | null = null;

    function pitch(semitones: number, base = 523.25): number {
        return base * 2 ** (semitones / 12);
    }

    function get_noise_buffer(context: AudioContext): AudioBuffer {
        if (!noise_buffer) {
            noise_buffer = context.createBuffer(1, context.sampleRate * 0.4, context.sampleRate);
            const samples = noise_buffer.getChannelData(0);
            for (let index = 0; index < samples.length; index += 1) {
                samples[index] = Math.random() * 2 - 1;
            }
        }
        return noise_buffer;
    }

    function arpeggio(
        semitones: number[],
        wave: OscillatorType,
        spacing: number,
        duration: number,
        volume: number,
    ): SoundNote[] {
        return semitones.map((step, index) => ({
            frequency: pitch(step),
            delay: index * spacing,
            duration: index === semitones.length - 1 ? duration * 2 : duration,
            volume,
            wave,
        }));
    }

    function sound_notes(
        sound: "enabled" | "start" | "good" | "bonus" | "shield" | "heart" | "hazard" | "blocked" | "level" | "finish",
    ): SoundNote[] {
        switch (sound) {
            case "enabled":
                return arpeggio([0, 4, 7], "triangle", 0.06, 0.09, 0.022);
            case "start":
                return arpeggio([-5, 0], "triangle", 0.09, 0.1, 0.03);
            case "good": {
                const step = streak_steps[Math.min(streak, streak_steps.length - 1)];
                return [{ frequency: pitch(step), end_frequency: pitch(step + 1), duration: 0.08, volume: 0.022 }];
            }
            case "bonus":
                return [
                    ...arpeggio([12, 16, 19, 24], "triangle", 0.055, 0.09, 0.03),
                    { frequency: pitch(36), delay: 0.2, duration: 0.25, volume: 0.008 },
                ];
            case "shield":
                return [{ frequency: 260, end_frequency: 1040, duration: 0.28, volume: 0.012, wave: "square" }];
            case "heart":
                return arpeggio([7, 14], "triangle", 0.11, 0.14, 0.035);
            case "hazard":
                return [
                    { frequency: 180, end_frequency: 70, duration: 0.4, volume: 0.03, wave: "sawtooth" },
                    { frequency: 180, end_frequency: 70, duration: 0.4, volume: 0.03, wave: "sawtooth", detune: 60 },
                    { frequency: 0, duration: 0.12, volume: 0.06, wave: "noise" },
                ];
            case "blocked":
                return [
                    { frequency: 0, duration: 0.05, volume: 0.04, wave: "noise" },
                    { frequency: 1400, duration: 0.18, volume: 0.01, wave: "square" },
                ];
            case "level":
                return arpeggio([0, 4, 7, 12, 16], "triangle", 0.08, 0.12, 0.035);
            case "finish":
                if (score > 0 && score > high_score) {
                    return arpeggio([0, 4, 7, 12, 7, 12], "triangle", 0.1, 0.12, 0.035);
                }
                return arpeggio([7, 3, 0, -5], "triangle", 0.16, 0.16, 0.03);
        }
    }

    function play_note(context: AudioContext, output: GainNode, note: SoundNote): void {
        const start = context.currentTime + (note.delay ?? 0);
        const end = start + note.duration;
        const envelope = context.createGain();
        envelope.gain.setValueAtTime(0.0001, start);
        envelope.gain.linearRampToValueAtTime(note.volume, start + 0.008);
        envelope.gain.exponentialRampToValueAtTime(0.0001, end);
        envelope.connect(output);

        let source: AudioScheduledSourceNode;
        if (note.wave === "noise") {
            const noise = context.createBufferSource();
            noise.buffer = get_noise_buffer(context);
            source = noise;
        } else {
            const oscillator = context.createOscillator();
            oscillator.type = note.wave ?? "sine";
            oscillator.detune.value = note.detune ?? 0;
            oscillator.frequency.setValueAtTime(note.frequency, start);
            if (note.end_frequency) {
                oscillator.frequency.exponentialRampToValueAtTime(note.end_frequency, end);
            }
            source = oscillator;
        }
        source.connect(envelope);
        source.addEventListener("ended", () => {
            source.disconnect();
            envelope.disconnect();
        });
        source.start(start);
        source.stop(end);
    }

    function play_sound(
        sound: "enabled" | "start" | "good" | "bonus" | "shield" | "heart" | "hazard" | "blocked" | "level" | "finish",
    ): void {
        if (!sound_enabled || !audio_context || !audio_output || audio_context.state !== "running") {
            return;
        }
        for (const note of sound_notes(sound)) {
            play_note(audio_context, audio_output, note);
        }
    }

    function multiplier(): number {
        return Math.min(3, 1 + Math.floor(streak / 5));
    }

    function update_status(): void {
        $score_output.textContent = String(score);
        $level_output.textContent = String(level);
        $combo_output.textContent = `×${multiplier()}`;
        $lives_output.textContent = Array.from({ length: 3 }, (_, index) => (index < lives ? "♥" : "♡")).join(" ");
        $lives_output.setAttribute("aria-label", `${lives} ${lives === 1 ? "leven" : "levens"}`);
        $high_score_output.textContent = high_score > 0 ? `Record: ${high_score}` : "Zet het eerste record";
        $catcher.classList.toggle("has-shield", shield_active);
        if (lives <= 0) {
            $catcher_face.textContent = "😵‍💫";
        } else if (lives === 1) {
            $catcher_face.textContent = "😰";
        } else if (lives === 2) {
            $catcher_face.textContent = "😅";
        } else if (shield_active) {
            $catcher_face.textContent = "😎";
        } else if (multiplier() === 3) {
            $catcher_face.textContent = "🤩";
        } else if (multiplier() === 2) {
            $catcher_face.textContent = "😄";
        } else {
            $catcher_face.textContent = "😊";
        }
    }

    function clear_items(): void {
        items.forEach(({ element }) => element.remove());
        items = [];
    }

    function show_message(emoji: string, title: string, body: string): void {
        $message_emoji.textContent = emoji;
        $message_title.textContent = title;
        $message_copy.textContent = body;
        $message.hidden = false;
    }

    function show_feedback(text: string): void {
        window.clearTimeout(feedback_timer);
        $feedback_output.classList.remove("show");
        $feedback_output.textContent = text;
        window.requestAnimationFrame(() => $feedback_output.classList.add("show"));
        feedback_timer = window.setTimeout(() => $feedback_output.classList.remove("show"), 700);
    }

    function refresh_geometry(): void {
        board_width = $board.clientWidth;
        board_height = $board.clientHeight;
        catcher_width = $catcher.offsetWidth;
        catcher_height = $catcher.offsetHeight;
        catcher_top = $catcher.offsetTop;
    }

    function celebrate_level(): void {
        play_sound("level");
        window.clearTimeout(level_toast_timer);
        $level_toast.textContent = `Level ${level}!`;
        $level_toast.hidden = false;
        level_toast_timer = window.setTimeout(() => ($level_toast.hidden = true), 1150);
        burst_confetti(12);
        $live_output.textContent = `Level ${level}. Het tempo gaat omhoog!`;
    }

    function choose_item_type(): ItemType {
        const chance = Math.random();
        const hazard_chance = Math.min(0.3, 0.18 + (level - 1) * 0.015);
        if (lives < 3 && spawns_since_damage >= 4) {
            return "heart";
        }
        if (chance < hazard_chance) {
            return "hazard";
        }
        if (chance < hazard_chance + 0.05) {
            return "shield";
        }
        const heart_chance = lives === 1 ? 0.15 : lives === 2 ? 0.09 : 0;
        if (chance < hazard_chance + 0.05 + heart_chance) {
            return "heart";
        }
        if (chance < hazard_chance + 0.15 + heart_chance) {
            return "bonus";
        }
        return "good";
    }

    function spawn_item(): void {
        const type = choose_item_type();
        if (type === "heart") {
            spawns_since_damage = 0;
        } else if (lives < 3) {
            spawns_since_damage += 1;
        }
        const good = good_items[Math.floor(Math.random() * good_items.length)];
        const hazard = hazard_items[Math.floor(Math.random() * hazard_items.length)];
        const definitions = {
            hazard,
            bonus: { emoji: "⭐", label: "bonusster" },
            shield: { emoji: "🛡️", label: "beschermschild" },
            heart: { emoji: "❤️", label: "extra hartje" },
            good,
        };
        const definition = definitions[type];
        const $element = document.createElement("div");
        const x = 6 + Math.random() * 88;
        $element.className = `falling-item is-${type}`;
        $element.textContent = definition.emoji;
        $element.setAttribute("role", "img");
        $element.setAttribute("aria-label", definition.label);
        $board.append($element);
        items.push({
            element: $element,
            size: $element.offsetWidth,
            x,
            y: -64,
            speed: 100 + level * 10 + Math.random() * 45,
            type,
        });
    }

    function finish(): void {
        play_sound("finish");
        running = false;
        cancelAnimationFrame(animation_frame);
        clear_items();
        movement = 0;
        shield_active = false;
        save_high_score();
        update_status();
        $start_label.textContent = "Nog een ronde";
        $play_status_output.textContent = "Mooie score!";
        show_message(
            "🌱",
            `Je verzamelde ${score} punten!`,
            `Je haalde level ${level}. Zin om je record te verbreken?`,
        );
        $live_output.textContent = `Ronde afgelopen met ${score} punten in level ${level}.`;
    }

    function burst_confetti(amount: number): void {
        const symbols = ["✦", "●", "▲", "★"];
        for (let index = 0; index < amount; index += 1) {
            const $confetti = document.createElement("span");
            $confetti.className = "falling-item";
            $confetti.ariaHidden = "true";
            $confetti.textContent = symbols[index % symbols.length];
            $confetti.style.left = `${8 + Math.random() * 84}%`;
            $confetti.style.top = `${5 + Math.random() * 35}%`;
            $confetti.style.color = ["#ff8800", "#9147d1", "#216e51", "#6f7914"][index % 4];
            $confetti.style.animation = `error-game-caught ${0.55 + Math.random() * 0.5}s ${Math.random() * 0.25}s ease-out forwards`;
            $board.append($confetti);
            window.setTimeout(() => $confetti.remove(), 1400);
        }
    }

    function check_collision(item: FallingItem): boolean {
        const item_center = (board_width * item.x) / 100;
        const item_left = item_center - item.size / 2;
        const item_right = item_left + item.size;
        const item_bottom = item.y + item.size;
        const catcher_left = (board_width * catcher_position) / 100 - catcher_width / 2;
        const catcher_right = catcher_left + catcher_width;
        const catcher_bottom = catcher_top + catcher_height;
        return (
            item_right > catcher_left &&
            item_left < catcher_right &&
            item_bottom > catcher_top &&
            item.y < catcher_bottom
        );
    }

    function catch_item(item: FallingItem): void {
        item.element.classList.add(item.type === "hazard" ? "is-hit" : "is-caught");
        window.setTimeout(() => item.element.remove(), 350);

        if (item.type === "hazard") {
            if (shield_active) {
                play_sound("blocked");
                shield_active = false;
                show_feedback("Schild gered! 🛡️");
                $live_output.textContent = "Je schild hield het obstakel tegen.";
            } else {
                play_sound("hazard");
                lives -= 1;
                spawns_since_damage = 0;
                streak = 0;
                show_feedback("Au! −1 ♥");
                $live_output.textContent = `Obstakel geraakt. Nog ${lives} ${lives === 1 ? "leven" : "levens"}.`;
            }
        } else if (item.type === "shield") {
            play_sound("shield");
            shield_active = true;
            streak += 1;
            show_feedback("Beschermd! 🛡️");
            $live_output.textContent = "Schild gevangen. De volgende wolk doet geen pijn.";
        } else if (item.type === "heart") {
            play_sound("heart");
            lives = Math.min(3, lives + 1);
            spawns_since_damage = 0;
            streak += 1;
            show_feedback("Extra leven! +1 ♥");
            $live_output.textContent = `Hartje gevangen. Je hebt weer ${lives} levens.`;
        } else {
            play_sound(item.type === "bonus" ? "bonus" : "good");
            streak += 1;
            const gained = (item.type === "bonus" ? 3 : 1) * multiplier();
            score += gained;
            show_feedback(item.type === "bonus" ? `Ster! +${gained}` : `+${gained}`);
            $live_output.textContent = `${gained} punten gevangen. Score ${score}.`;
            const new_level = Math.floor(score / 20) + 1;
            if (new_level > level) {
                level = new_level;
                celebrate_level();
            }
        }
        save_high_score();
        update_status();
    }

    function game_loop(timestamp: number): void {
        if (!running) {
            return;
        }
        const delta = Math.min((timestamp - last_frame) / 1000, 0.04);
        last_frame = timestamp;
        catcher_position = Math.max(6, Math.min(94, catcher_position + movement * delta * 58));
        $catcher.style.left = `${catcher_position}%`;

        if (timestamp - last_spawn > Math.max(360, 820 - level * 35)) {
            spawn_item();
            last_spawn = timestamp;
        }

        let game_over = false;
        items = items.filter((item) => {
            item.y += item.speed * delta;
            item.element.style.left = `${item.x}%`;
            item.element.style.transform = `translate(-50%, ${item.y}px) rotate(${item.y * 0.08}deg)`;

            if (check_collision(item)) {
                catch_item(item);
                game_over = lives <= 0;
                return false;
            }
            if (item.y > board_height) {
                item.element.remove();
                if (item.type !== "hazard" && item.type !== "shield" && item.type !== "heart") {
                    streak = 0;
                    update_status();
                }
                return false;
            }
            return true;
        });

        if (game_over) {
            finish();
            return;
        }
        animation_frame = requestAnimationFrame(game_loop);
    }

    function start_game(): void {
        void enable_audio().then(() => play_sound("start"));
        cancelAnimationFrame(animation_frame);
        clear_items();
        score = 0;
        level = 1;
        lives = 3;
        streak = 0;
        shield_active = false;
        spawns_since_damage = 0;
        catcher_position = 50;
        movement = 0;
        pressed_directions.clear();
        running = true;
        $message.hidden = true;
        $level_toast.hidden = true;
        $catcher.style.left = "50%";
        refresh_geometry();
        $start_label.textContent = "Opnieuw beginnen";
        $play_status_output.textContent = "Blijf vangen!";
        update_status();
        $live_output.textContent = "Het spel is gestart. Vang gekleurde items en ontwijk grijze wolken.";
        $board.focus();
        last_frame = performance.now();
        last_spawn = last_frame - 500;
        animation_frame = requestAnimationFrame(game_loop);
    }

    function keyboard_movement(event: KeyboardEvent, active: boolean): void {
        if (!running || !["ArrowLeft", "ArrowRight", "a", "A", "d", "D"].includes(event.key)) {
            return;
        }
        if (document.activeElement !== $board && !$board.contains(document.activeElement)) {
            return;
        }
        event.preventDefault();
        const direction = ["ArrowLeft", "a", "A"].includes(event.key) ? "left" : "right";
        if (active) {
            pressed_directions.add(direction);
            movement = direction === "left" ? -1 : 1;
            if (!event.repeat) {
                catcher_position = Math.max(6, Math.min(94, catcher_position + movement * 1.5));
                $catcher.style.left = `${catcher_position}%`;
            }
            return;
        }
        pressed_directions.delete(direction);
        movement = pressed_directions.has("right") ? 1 : pressed_directions.has("left") ? -1 : 0;
    }

    $start_button.addEventListener("click", start_game);
    $sound_toggle.addEventListener("click", () => {
        sound_enabled = !sound_enabled;
        update_sound_toggle();
        try {
            window.sessionStorage.setItem("leervonk-sound-enabled", String(sound_enabled));
        } catch {
            // The toggle still works for this page when storage is unavailable.
        }
        if (sound_enabled) {
            void enable_audio().then(() => play_sound("enabled"));
        }
    });
    const { signal } = window.okl_page;
    window.addEventListener("keydown", (event) => keyboard_movement(event, true), { signal });
    window.addEventListener("keyup", (event) => keyboard_movement(event, false), { signal });
    window.addEventListener(
        "blur",
        () => {
            pressed_directions.clear();
            movement = 0;
        },
        { signal },
    );
    window.addEventListener("resize", refresh_geometry, { signal });

    $board.addEventListener("pointermove", (event) => {
        if (!running || (event.pointerType === "mouse" && event.buttons === 0)) {
            return;
        }
        const rect = $board.getBoundingClientRect();
        catcher_position = ((event.clientX - rect.left) / rect.width) * 100;
    });
    $board.addEventListener("click", (event) => {
        if (!running) {
            return;
        }
        const rect = $board.getBoundingClientRect();
        catcher_position = ((event.clientX - rect.left) / rect.width) * 100;
    });

    $$move_buttons.forEach(($button) => {
        const direction = $button.dataset.move === "left" ? -1 : 1;
        $button.addEventListener("pointerdown", (event) => {
            event.preventDefault();
            movement = direction;
            $button.classList.add("is-pressed");
            $button.setPointerCapture(event.pointerId);
        });
        function stop_moving(): void {
            movement = 0;
            $button.classList.remove("is-pressed");
        }
        $button.addEventListener("pointerup", stop_moving);
        $button.addEventListener("pointercancel", stop_moving);
    });

    document.addEventListener(
        "visibilitychange",
        () => {
            if (!running) {
                return;
            }
            if (document.hidden) {
                cancelAnimationFrame(animation_frame);
            } else {
                last_frame = performance.now();
                last_spawn = last_frame;
                animation_frame = requestAnimationFrame(game_loop);
            }
        },
        { signal },
    );
    signal.addEventListener(
        "abort",
        () => {
            running = false;
            cancelAnimationFrame(animation_frame);
            window.clearTimeout(feedback_timer);
            window.clearTimeout(level_toast_timer);
            clear_items();
            void audio_context?.close();
        },
        { once: true },
    );
    update_status();
    update_sound_toggle();
}

window.on_okl_ready(initialize_error_game);
document.addEventListener("htmx:afterSettle", () => {
    window.on_okl_ready(initialize_error_game);
});
