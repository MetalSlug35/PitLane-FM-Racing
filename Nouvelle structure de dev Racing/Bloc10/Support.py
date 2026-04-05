# =============================================================================
#  Bloc10 - Support.py
#  Popup de soutien "Buy Me a Coffee" (affiche une seule fois).
#  Module universel - aucune dependance a un jeu specifique.
#
#  API publique :
#    afficher(
#      app_title, message, donate_url, nexus_url,
#      language, logo_path, ui_texts
#    ) -> bool
# =============================================================================

import os
import sys
import webbrowser


DEFAULT_UI_TEXTS = {
    "close": {
        "fr": "Fermer",
        "en": "Close",
        "de": "Schliessen",
        "it": "Chiudi",
        "es": "Cerrar",
        "pt": "Fechar",
        "zh": "关闭",
        "ja": "闭じる",
    },
    "coffee": {
        "fr": "Soutenir le projet",
        "en": "Support the project",
        "de": "Projekt unterstuetzen",
        "it": "Supporta il progetto",
        "es": "Apoyar el proyecto",
        "pt": "Apoiar o projeto",
        "zh": "支持这个项目",
        "ja": "プロジェクトを支援する",
    },
    "nexus": {
        "fr": "Voir mes mods Nexus",
        "en": "See my Nexus mods",
        "de": "Meine Nexus-Mods ansehen",
        "it": "Vedi le mie mod su Nexus",
        "es": "Ver mis mods de Nexus",
        "pt": "Ver os meus mods na Nexus",
        "zh": "查看我的 Nexus 模组",
        "ja": "Nexus Mods を見る",
    },
    "optional": {
        "fr": "C'est totalement facultatif.",
        "en": "This is completely optional.",
        "de": "Das ist komplett optional.",
        "it": "E totalmente facoltativo.",
        "es": "Es totalmente opcional.",
        "pt": "E totalmente opcional.",
        "zh": "这完全是自愿的。",
        "ja": "完全に任意です。",
    },
    "once": {
        "fr": "Cette fenetre ne s'affichera plus, sauf si tu reinstalles le mod.",
        "en": "This window will not appear again unless you reinstall the mod.",
        "de": "Dieses Fenster erscheint nicht erneut, ausser du installierst den Mod neu.",
        "it": "Questa finestra non comparira piu, salvo reinstallazione della mod.",
        "es": "Esta ventana no volvera a aparecer salvo reinstalacion del mod.",
        "pt": "Esta janela nao voltara a aparecer, salvo reinstalacao do mod.",
        "zh": "除非你重新安装模组，否则这个窗口不会再次出现。",
        "ja": "このウィンドウは、Mod を再インストールしない限り再表示されません。",
    },
}


DEFAULT_MESSAGES = {
    "fr": (
        "Si le mod te plait et t'accompagne pendant tes sessions, tu peux me donner "
        "un petit coup de pouce avec un cafe.\n\n"
        "Aucune obligation bien sur : le mod reste pleinement utilisable sans don.\n\n"
        "Si tu veux suivre le projet, poser une question ou voir mes autres creations, "
        "ma page Nexus est juste en dessous."
    ),
    "en": (
        "If you enjoy the mod and it is making your sessions better, you can give me "
        "a little boost with a coffee.\n\n"
        "Of course, this is completely optional: the mod stays fully usable without any donation.\n\n"
        "If you want to follow the project, ask questions, or check out my other work, "
        "my Nexus page is right below."
    ),
    "de": (
        "Wenn dir der Mod gefaellt und deine Sessions verbessert, kannst du mich mit "
        "einem Kaffee unterstuetzen.\n\n"
        "Natuerlich ist das komplett optional: Der Mod bleibt auch ohne Spende voll nutzbar.\n\n"
        "Wenn du dem Projekt folgen, Fragen stellen oder meine anderen Arbeiten sehen willst, "
        "findest du meine Nexus-Seite direkt unten."
    ),
    "it": (
        "Se la mod ti piace e rende migliori le tue sessioni, puoi darmi una piccola mano "
        "offrendomi un caffe.\n\n"
        "Naturalmente e del tutto facoltativo: la mod resta pienamente utilizzabile anche senza donazioni.\n\n"
        "Se vuoi seguire il progetto, fare domande o vedere i miei altri lavori, "
        "trovi qui sotto la mia pagina Nexus."
    ),
    "es": (
        "Si te gusta el mod y hace mas agradables tus sesiones, puedes echarme una mano "
        "invitandome a un cafe.\n\n"
        "Por supuesto, es totalmente opcional: el mod sigue siendo totalmente util sin donar.\n\n"
        "Si quieres seguir el proyecto, hacer preguntas o ver mis otros trabajos, "
        "mi pagina de Nexus esta justo abajo."
    ),
    "pt": (
        "Se gostas do mod e ele melhora as tuas sessoes, podes dar-me uma pequena ajuda "
        "oferecendo-me um cafe.\n\n"
        "Claro que e totalmente opcional: o mod continua totalmente utilizavel sem doacoes.\n\n"
        "Se quiseres acompanhar o projeto, fazer perguntas ou ver os meus outros trabalhos, "
        "a minha pagina Nexus esta logo abaixo."
    ),
    "zh": (
        "如果你喜欢这个模组，并且它让你的游戏过程更舒服，你可以请我喝一杯咖啡来支持我。\n\n"
        "当然，这完全是自愿的：即使不捐赠，模组也依然可以完整使用。\n\n"
        "如果你想关注项目、提问，或者看看我的其他作品，下面就是我的 Nexus 页面。"
    ),
    "ja": (
        "この Mod が気に入っていて、走行中の体験が良くなったと感じてくれたなら、"
        "コーヒーで少し応援してもらえると嬉しいです。\n\n"
        "もちろん完全に任意で、寄付がなくても Mod はそのまましっかり使えます。\n\n"
        "プロジェクトを追いかけたい時や質問したい時、ほかの作品を見たい時は、"
        "下の Nexus ページを使ってください。"
    ),
}


def _ui_text(key: str, language: str, ui_texts: dict) -> str:
    values = ui_texts.get(key, DEFAULT_UI_TEXTS.get(key, {}))
    return values.get(language) or values.get("en", key)


def _get_message(language: str, message_override: str = "") -> str:
    if message_override:
        return message_override
    return DEFAULT_MESSAGES.get(language) or DEFAULT_MESSAGES.get("en", "")


def _resolve_support_asset(filename: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    exe_dir = os.path.dirname(getattr(sys, "executable", ""))
    meipass = getattr(sys, "_MEIPASS", "")
    base_dirs = [
        here,
        os.path.dirname(here),
        os.path.dirname(os.path.dirname(here)),
        meipass,
        exe_dir,
        os.path.join(exe_dir, "_internal"),
    ]
    candidates = []
    for base in base_dirs:
        if not base:
            continue
        candidates.extend([
            os.path.join(base, filename),
            os.path.join(base, "Bloc11", "ressource", filename),
        ])
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def _load_image(tk_module, image_path: str, max_width: int, max_height: int):
    if not image_path or not os.path.exists(image_path):
        return None

    try:
        from PIL import Image, ImageTk

        with Image.open(image_path) as img:
            ratio = min(max_width / img.width, max_height / img.height, 1.0)
            size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
            if size != img.size:
                img = img.resize(size, Image.LANCZOS)
            return ImageTk.PhotoImage(img)
    except Exception:
        try:
            return tk_module.PhotoImage(file=image_path)
        except Exception:
            return None


def afficher(
    app_title: str = "PitLane FM",
    message: str = "",
    donate_url: str = "",
    nexus_url: str = "",
    language: str = "en",
    logo_path: str = "",
    ui_texts: dict = None,
) -> bool:
    """
    Affiche le popup de soutien.
    Retourne True si le popup a ete affiche jusqu'a sa fermeture.
    """
    try:
        import tkinter as tk
    except Exception:
        return False

    ui_texts = ui_texts or {}
    msg_text = _get_message(language, message)
    donate_url = donate_url or "https://buymeacoffee.com/MetalSlug"
    nexus_url = nexus_url or "https://www.nexusmods.com/profile/MetalSlug35/mods"
    coffee_logo_path = _resolve_support_asset("buy_me_a_coffee_logo.png")

    root = tk.Tk()
    root.title(app_title)
    root.configure(bg="#070b12")
    root.resizable(False, False)
    root.lift()
    root.attributes("-topmost", True)
    root.after(250, lambda: root.attributes("-topmost", False))

    app_logo = _load_image(tk, logo_path, 96, 96)
    if app_logo is not None:
        try:
            root.iconphoto(True, app_logo)
        except Exception:
            pass

    coffee_logo = _load_image(tk, coffee_logo_path, 190, 190)

    def _open_donate():
        try:
            webbrowser.open(donate_url)
        except Exception:
            pass

    def _open_nexus():
        try:
            webbrowser.open(nexus_url)
        except Exception:
            pass

    def _close():
        root.destroy()

    card = tk.Frame(
        root,
        bg="#11192a",
        bd=0,
        highlightthickness=1,
        highlightbackground="#24324d",
        padx=26,
        pady=24,
    )
    card.pack(fill="both", expand=True, padx=18, pady=18)

    tk.Frame(card, bg="#ff2f63", height=5).pack(fill="x", pady=(0, 18))

    header = tk.Frame(card, bg="#11192a")
    header.pack(fill="x")

    title_block = tk.Frame(header, bg="#11192a")
    title_block.pack(side="left", fill="x", expand=True)

    tk.Label(
        title_block,
        text=app_title,
        font=("Segoe UI Semibold", 20),
        fg="#f7f7fb",
        bg="#11192a",
        anchor="w",
    ).pack(anchor="w")

    tk.Label(
        title_block,
        text=_ui_text("optional", language, ui_texts),
        font=("Segoe UI", 10),
        fg="#9fb0cf",
        bg="#11192a",
        anchor="w",
    ).pack(anchor="w", pady=(6, 0))

    content = tk.Frame(card, bg="#11192a")
    content.pack(fill="both", expand=True, pady=(18, 12))

    text_panel = tk.Frame(content, bg="#11192a")
    text_panel.pack(side="left", fill="both", expand=True, padx=(0, 20))

    tk.Message(
        text_panel,
        text=msg_text,
        width=470,
        justify="left",
        font=("Segoe UI", 12),
        fg="#e8ebf2",
        bg="#11192a",
    ).pack(anchor="w", fill="x")

    info_box = tk.Frame(
        text_panel,
        bg="#0f2136",
        highlightthickness=1,
        highlightbackground="#21466f",
        padx=14,
        pady=12,
    )
    info_box.pack(fill="x", pady=(16, 0))

    tk.Label(
        info_box,
        text=_ui_text("once", language, ui_texts),
        justify="left",
        wraplength=430,
        font=("Segoe UI", 10),
        fg="#cfe3ff",
        bg="#0f2136",
    ).pack(anchor="w")

    action_panel = tk.Frame(content, bg="#0d1422", padx=18, pady=18)
    action_panel.pack(side="right", fill="y")

    tk.Button(
        action_panel,
        text=_ui_text("coffee", language, ui_texts),
        command=_open_donate,
        bd=0,
        relief="flat",
        highlightthickness=0,
        cursor="hand2",
        bg="#ff2f63",
        activebackground="#e12257",
        fg="#ffffff",
        activeforeground="#ffffff",
        font=("Segoe UI Semibold", 11),
        padx=18,
        pady=12,
        width=22,
    ).pack(fill="x")

    if nexus_url:
        tk.Button(
            action_panel,
            text=_ui_text("nexus", language, ui_texts),
            command=_open_nexus,
            bd=0,
            relief="flat",
            highlightthickness=0,
            cursor="hand2",
            bg="#1b4f8a",
            activebackground="#163f6d",
            fg="#ffffff",
            activeforeground="#ffffff",
            font=("Segoe UI Semibold", 11),
            padx=18,
            pady=12,
            width=22,
        ).pack(fill="x", pady=(10, 0))

    tk.Frame(action_panel, bg="#0d1422").pack(fill="both", expand=True)

    if coffee_logo is not None:
        legacy_coffee_btn = tk.Button(
            action_panel,
            image=coffee_logo,
            command=_open_donate,
            bd=0,
            relief="flat",
            highlightthickness=0,
            cursor="hand2",
            bg="#0d1422",
            activebackground="#0d1422",
        )
        legacy_coffee_btn.pack(side="bottom", pady=(16, 2))
        legacy_coffee_btn.image = coffee_logo

    footer = tk.Frame(card, bg="#11192a")
    footer.pack(fill="x", pady=(10, 0))

    tk.Button(
        footer,
        text=_ui_text("close", language, ui_texts),
        command=_close,
        bd=0,
        relief="flat",
        highlightthickness=0,
        cursor="hand2",
        bg="#ff2f63",
        activebackground="#e12257",
        fg="#ffffff",
        activeforeground="#ffffff",
        font=("Segoe UI Semibold", 11),
        padx=22,
        pady=10,
    ).pack(side="right")

    if app_logo is not None:
        root._app_logo = app_logo
    if coffee_logo is not None:
        root._coffee_logo = coffee_logo

    root.protocol("WM_DELETE_WINDOW", _close)
    root.update_idletasks()

    width = min(max(820, root.winfo_reqwidth()), max(820, root.winfo_screenwidth() - 80))
    height = min(max(540, root.winfo_reqheight()), max(540, root.winfo_screenheight() - 80))
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")

    root.mainloop()
    return True
