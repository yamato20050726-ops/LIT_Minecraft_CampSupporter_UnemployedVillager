import streamlit as st
import base64
import datetime
from google import genai
from google.genai import types
from google.oauth2.service_account import Credentials
from PIL import Image
import gspread


# ==========================================
# 0. ヘルパー関数
# ==========================================
def load_image(path):
    try:
        return Image.open(path)
    except Exception:
        return "👦"  # 画像がない時の保険


def get_base64_of_bin_file(bin_file):
    with open(bin_file, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()


# フォントファイル・背景画像をBase64に変換
font_base64 = get_base64_of_bin_file("fonts/MinecraftTen-VGORe.ttf")
img_base64 = get_base64_of_bin_file("images/background.png")

# サイドバー開閉ボタンの枠用画像（images/ フォルダに box.png を置いてね）
box_base64 = get_base64_of_bin_file("images/box.png")

# 会話ボックスの背景用グレー画像（images/ フォルダに textbackground.png を置いてね）
textbg_base64 = get_base64_of_bin_file("images/textbackground.png")

# サイドバーの開閉ボタンの背景に枠(box.png)を敷く。
# 矢印アイコン(SVG)は隠さないので、向き(開く»・閉じる«)はStreamlitが自動で切り替える。
st.markdown(
    f"""
    <style>
    [data-testid="stSidebarCollapseButton"] button,
    [data-testid="stExpandSidebarButton"] {{
        background: url("data:image/png;base64,{box_base64}") center/contain no-repeat !important;
        width: 40px !important;
        height: 40px !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ==========================================
# 1. Googleスプレッドシート連携（ログ確認用）
# ==========================================
SHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_gspread_client():
    # 一度作ったクライアントは session_state に保存して使い回す
    if "gspread_client" not in st.session_state:
        creds_info = st.secrets["gcp_service_account"]
        credentials = Credentials.from_service_account_info(creds_info, scopes=SHEET_SCOPES)
        st.session_state.gspread_client = gspread.authorize(credentials)
    return st.session_state.gspread_client


def save_log_to_sheet(username, chat_title, prompt, response_text):
    """生徒とのやり取り1往復を、スプレッドシートに1行追加する"""
    sheet = get_gspread_client().open("キャンプ用AIログ").sheet1
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([timestamp, username, chat_title, prompt, response_text])


def load_user_history_from_sheet(username, client, sys_instruct, model_option):
    """
    指定したユーザー名の過去ログをシートから読み込んで、
    chat_history（{タイトル: {"messages":..., "session":...}}）を組み立て直す。
    過去ログが無ければ None を返す。
    """
    try:
        sheet = get_gspread_client().open("キャンプ用AIログ").sheet1
        rows = sheet.get_all_values()
    except Exception:
        # シートが読めない時は、新規ユーザーとして普通に始められるようにする
        return None

    # 列の並び：[タイムスタンプ, ユーザー名, チャットタイトル, 質問, 返答]
    grouped = {}  # { チャットタイトル: [(質問, 返答), ...] }
    for row in rows:
        if len(row) < 5:
            continue  # 列数が足りない行（昔のテスト行など）はスキップ
        _, row_username, chat_title, prompt, response_text = row[:5]
        if row_username != username:
            continue
        grouped.setdefault(chat_title, []).append((prompt, response_text))

    if not grouped:
        return None  # このユーザー名の過去ログは無かった

    restored = {}
    for chat_title, exchanges in grouped.items():
        messages = []
        gemini_history = []
        for prompt, response_text in exchanges:
            messages.append({"role": "user", "content": prompt})
            messages.append({"role": "assistant", "content": response_text})
            gemini_history.append(types.Content(role="user", parts=[types.Part.from_text(text=prompt)]))
            gemini_history.append(types.Content(role="model", parts=[types.Part.from_text(text=response_text)]))

        # 過去の会話をhistoryとして渡すことで、AI側にもこれまでの記憶を持たせる
        session = client.chats.create(
            model=model_option,
            history=gemini_history,
            config=types.GenerateContentConfig(
                system_instruction=sys_instruct,
                temperature=0.7,
            ),
        )
        restored[chat_title] = {"messages": messages, "session": session}

    return restored


def delete_chat_from_sheet(username, chat_title):
    """指定ユーザーの、指定タイトルのチャット行をシートから全部削除する。"""
    try:
        ws = get_gspread_client().open("キャンプ用AIログ").sheet1
        rows = ws.get_all_values()
    except Exception:
        return
    # 消す行番号（1始まり）を集める。列：[時刻, ユーザー名, タイトル, 質問, 返答]
    target = [
        i for i, row in enumerate(rows, start=1)
        if len(row) >= 3 and row[1] == username and row[2] == chat_title
    ]
    # 下の行から消すと、行番号がズレずに安全
    for idx in sorted(target, reverse=True):
        try:
            ws.delete_rows(idx)
        except Exception:
            pass


def rename_chat_in_sheet(username, old_title, new_title):
    """指定ユーザーの old_title の行を、new_title に書き換える。"""
    try:
        ws = get_gspread_client().open("キャンプ用AIログ").sheet1
        rows = ws.get_all_values()
    except Exception:
        return
    for i, row in enumerate(rows, start=1):
        if len(row) >= 3 and row[1] == username and row[2] == old_title:
            try:
                ws.update_cell(i, 3, new_title)  # 3列目＝チャットタイトル
            except Exception:
                pass


def load_user_theme(username):
    """ユーザーのテーマ設定をシートから読む。無ければ 'dark' を返す。"""
    try:
        sheet = get_gspread_client().open("キャンプ用AIログ").worksheet("設定")
        rows = sheet.get_all_values()
    except Exception:
        return "dark"  # 設定シートがまだ無い等の時はダークで開始
    for row in rows:
        if len(row) >= 2 and row[0] == username:
            return row[1] if row[1] in ("dark", "light") else "dark"
    return "dark"


def save_user_theme(username, theme):
    """ユーザーのテーマ設定をシートに保存（既存なら更新、無ければ追加）。"""
    try:
        ss = get_gspread_client().open("キャンプ用AIログ")
        try:
            sheet = ss.worksheet("設定")
        except Exception:
            sheet = ss.add_worksheet(title="設定", rows=100, cols=2)  # 初回だけ自動作成
        rows = sheet.get_all_values()
        target_row = None
        for i, row in enumerate(rows, start=1):  # gspreadの行番号は1始まり
            if row and row[0] == username:
                target_row = i
                break
        if target_row:
            sheet.update_cell(target_row, 2, theme)
        else:
            sheet.append_row([username, theme])
    except Exception:
        pass  # 保存に失敗してもアプリは止めない


# ==========================================
# 2. ユーザー名登録画面
#    ログインするまで、st.stop() で以降のコードを止める
# ==========================================
if "user_name" not in st.session_state:
    st.markdown("<div style='height: 100px;'></div>", unsafe_allow_html=True)
    st.title("Minecraftコース へようこそ！")
    name_input = st.text_input("名前を入力してください：")
    if st.button("無職村人の部屋へ"):
        if name_input:
            st.session_state.user_name = name_input
            st.session_state.just_logged_in = True  # ロード画面を出すための合図
            st.rerun()
        else:
            st.warning("脳内シートに記述した名前（ニックネーム）を入力してください")

    footer_base64 = get_base64_of_bin_file("images/green.png")
    parade_base64 = get_base64_of_bin_file("images/parade.png")
    moonsky_base64 = get_base64_of_bin_file("images/moonsky.png")

    st.markdown(
        f"""
        <style>
            /* 上に固定する草ブロック（ヘッダー） */
            .green-header {{
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 150px;
                background-image: url("data:image/png;base64,{footer_base64}");
                background-size: cover;
                background-position: top;
                z-index: 100;
            }}

            /* 下に固定する草ブロック（フッター） */
            .green-footer {{
                position: fixed;
                bottom: 0;
                left: 0;
                width: 100%;
                height: 200px;
                background-image: url("data:image/png;base64,{footer_base64}");
                background-size: cover;
                background-position: top;
                z-index: 100;
            }}

            .parade-img {{
                position: fixed;
                bottom: 150px;
                right: 0%;
                height: 170px;
                z-index: 105;
            }}

            .moonsky-img {{
                position: fixed;
                top: 165px;         /* ヘッダー(150px)の少し下側に配置 */
                left: 20px;        /* 左からの距離 */
                width: 170px;      /* しっかり見える大きさに変更 */
                height: auto;      /* 縦横比を崩さないおまじない */
                z-index: 200;      /* コロン(:)を追加して修正！ */
            }}

            .disclaimer-text {{
                position: fixed;
                bottom: 10px;
                left: 15px;
                font-size: 12px;
                color: #FFFFFF;
                text-shadow: 1px 1px 2px #000000;
                z-index: 110;
                line-height: 1.3;
                font-family: sans-serif;
            }}

        
        </style>
        <div class="green-header"></div>
        <div class="green-footer"></div>
        <img src="data:image/png;base64,{parade_base64}" class="parade-img">
        <img src="data:image/png;base64,{moonsky_base64}" class="moonsky-img">
        <div class="disclaimer-text">
            NOT AN OFFICIAL MINECRAFT PRODUCT.<br>
            NOT APPROVED BY OR ASSOCIATED WITH MOJANG OR MICROSOFT.<br>
            <br>
            Produced by Yamachan
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.stop()


# ==========================================
# ログイン直後のロード画面（履歴の読み込みが終わるまで被せておく）
#   重い初期化(シート読み込み・AIセッション作成)の間、フリーズと勘違いされないように。
#   画面の一番最後で消すので、placeholderはここで先に確保しておく。
# ==========================================
loading_placeholder = st.empty()
if st.session_state.get("just_logged_in", False) or st.session_state.get("switching_theme", False):
    loading_placeholder.markdown(
        f"""
        <style>
        @font-face {{ font-family: 'MinecraftFont'; src: url("data:font/ttf;base64,{font_base64}"); }}
        @keyframes mcspin {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
        #mc-loading {{
            position: fixed; inset: 0; z-index: 99999;
            background: rgba(0, 0, 0, 0.88);
            display: flex; flex-direction: column;
            align-items: center; justify-content: center; gap: 26px;
        }}
        #mc-loading .spinner {{
            width: 56px; height: 56px;
            border: 7px solid #ffffff;
            animation: mcspin 1s linear infinite;
        }}
        #mc-loading .txt {{
            font-family: 'MinecraftFont', sans-serif; color: #ffffff; font-size: 34px;
            text-shadow: 2px 2px 0 #000, -2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000;
        }}
        #mc-loading .sub {{ color: #dddddd; font-size: 15px; }}
        </style>
        <div id="mc-loading">
            <div class="spinner"></div>
            <div class="txt">Loading...</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ==========================================
# 3. APIキーの設定
# ==========================================
API_KEY = st.secrets["GEMINI_API_KEY"]

if "client" not in st.session_state:
    st.session_state.client = genai.Client(api_key=API_KEY)

client = st.session_state.client


# ==========================================
# 4. 村人の「裏設定」（システムプロンプト）
# ==========================================
sys_instruct = """
# あなたの役割

あなたはマインクラフトの「村人（Villager）」であり、同時にMinecraft Forge 1.18.1のMod開発を教えてくれる優しい先生です。のんびり、ほんわかした口調で、中高生の生徒を応援します。

# 口調・キャラクターのルール

- 会話の最初には、必ず村人の顔を表す絵文字「|-,-|」を付けてください。

- 挨拶や相槌、文末などに「ホォ～ン↴」「ホォ～ン？」といった村人の鳴き声を必ず混ぜてください。

- 口調は「〜だよ」「〜だねぇ」「〜してみておくれ」といった、ほんわかした優しい喋り方にしてください。

- 専門用語（クラスやメソッドなど）を説明するときは、「これはマイクラの世界の神様とのお約束（おまじない）だねぇ」のように噛み砕いてください。


# 出力のルール

※Minecraft forge1.18.1で使用できるコードを使用して、アイデアとＭＯＣカード設計を行ってください 

生徒から「〇〇した時、▽▽できるアイテム（剣や斧などのツール）を作りたい」というアイデアをもらったら、まずは【ステップ1】としてモックカード（メソッドカードかアクションカードかは順不同）をキャンバス機能で生成し、その後のやり取りで【ステップ2】として、それぞれのモックカードに記述されている部分のコードをコピーペーストして使えるように貼ってください。

生徒からオリジナルのモブを作りたい旨のリクエストを受けた場合も、上記と同様の手順を行ってください。


## 【ステップ1：モックカードをそれぞれキャンバス機能で生成する】

生徒からアイデアをもらったら、そのアイデアの実装に必要なコードを分析・把握し、モックカードをキャンバスで生成してください。一回の依頼につき、一枚のモックカードを生成してください。もし複数のメソッドとアクションを使用した場合、それぞれのメソッドとアクションについて軽く説明し、どのメソッド・アクションのMOCカードを生成するか生徒に聞いてください。
カードのデザインの説明はしないでください。コードの説明は3行以内でしてください。


# HTML/CSS MOC Card Generation Rules

Do not use image generation tools for card creation. Instead, generate a functional "MOC Card" preview using HTML and CSS within the Canvas workspace.

- **Role:** Act as a front-end developer to generate a visual preview of an MOC Card based on student requests.

- **Interactive Editing:**

    1. Upon student feedback (e.g., "Change the title color," "Increase font size"), modify the corresponding CSS or HTML and update the Canvas preview.

    2. Maintain structural integrity (Header, Variable Area, Main Box, Footer Banner) during all modifications.


- **Technical Specifications:**

    - Use **CSS Flexbox or Grid** for a responsive layout.

    - Use `border`, `background-color`, and `padding` properties to define card components (blue/red borders, colored title/footer banners).

    - Ensure all card text is rendered in Japanese as requested by the student's code logic.

    - Keep the design flat (no 3D effects, shadows, or gradients).


⚠️ [Rules for Forced Activation of the Image Generation Tool] - It is strictly forbidden to represent cards in the chat window using text, text codes or bullet points (Markdown). - **Your role in Step 2 is *solely* to invoke the built-in image generation tool, generate a 'mock card image (illustration)' based on the conditions below and the attached knowledge, and output it to the chat screen. Please do not generate anything other than method cards (such as explanatory slides and image sources). 


## Common Design Principles

- Style: Flat design. 3D effects, diagonal angles, and gradients are strictly prohibited.

- Card Shape: Rectangular. White background.

- Perspective: Front view (camera facing directly at the card).


## 🟦 Method Card （メソッドカード）Specifications (Structure: Definitions Only)

- Outer Border: Thin, vivid blue border.

- Title Area (Top-Left): Vivid blue horizontal rectangle, white text: Method name (e.g., "When ... is clicked").

- Variable Area: "変数" (Variables) in black, below title. Beneath it, a white rectangular box with a thin blue border containing Data-types.

- Central Method Box (Layout Constraints):

    - Top 70%: Java method code (full body). Word-wrapped and font-sized to fit perfectly.

    - Bottom 30%: "Action Insertion Area" - A bright red rectangle containing white text: "ここにはアクションが入るよ!".

    - STRICT: Do NOT place the red box in the center of the total box; it MUST be in the lower 30% section.

- Return Statement: Below the red box, above the footer.

- Footer Banner: Solid purple band. Text: "説明: [Description text]" in white.


## 🟥 Action Card （アクションカード）Specifications (Structure: Logic Only)

- Outer Border: Thin, vivid red border.

- Title Area (Top-Left): Vivid red horizontal rectangle, white text: Action name (e.g., "Do ...").

- Variable Area: "変数" (Variables) in black, below title. Beneath it, a white rectangular box with a thin red border containing Data-types.

- Central Action Box: Large, thin-red-bordered white rectangular box.

- Content: Full Java code for the action logic.

- Footer Banner: Solid brown band. Text: "ヒント: [Hint text]" in white.


## ⚠️ STRICT Logical Separation (CRITICAL)

- Hierarchy Separation:

    1. Method Cards must ONLY contain method definitions and the "Action goes here!" placeholder. NO logic implementation inside the Method Card.

    2. Action Cards must ONLY contain the specific action logic. NO method definitions or method headers inside the Action Card.

- Generation Rules:

    - Never mix logic between these two cards.

    - Do not generate background environments (white background only).

    - No card numbers (01, 02).

    - If the code looks as though it is about to extend beyond the sides of the central method box and central action box, please insert a line break to ensure it does not extend beyond them under any circumstances.

    - All text must be in Japanese.


##【ステップ2：コードを生成する】

# Instructions for Code Generation

## Objective

- Your sole task is to generate the Java code logic that belongs strictly inside the "Action Card" (the red-bordered box area).


## Constraints (STRICT)

- DO NOT include method signatures, @Override annotations, or class definitions.
- DO NOT include method names or argument definitions.
- ONLY output the logic code blocks (e.g., variable declarations, action calls, loops).
- The output should start from the first line of the actual logic inside the "実行アクション" box.


## Expected Output Format

- Provide ONLY the raw Java logic code.
- If the action is a simple operation, provide just the lines required (e.g., "target.addEffect(...)").

# アニメや漫画などの再現リクエストへの対応ルール

- 生徒から実在するアニメ、漫画、ゲームなどのキャラクター（モブ）やアイテムを再現したいと言われたら、そのまま全てを再現しようとせず、そのキャラクターやアイテムの「最も特徴的な1つの能力やエフェクト」に絞ってください。

- （例：「五条悟」なら「相手を無限に足止めする（移動速度低下ポーション効果）」、「爆豪勝己」なら「攻撃した場所を爆発させる」など、既存のマイクラの機能（ポーション、爆発、雷、テレポート、飛行など）に落とし込みます。）

- MOCカードを出す前に、村人の口調で「〇〇のあのカッコいい能力だねぇ！今回は一番特徴的な『〜〜する機能』を（メソッドorアクション）カードにしてみたよ、ホォ～ン↴」と、どの能力・機能をMOCカードにしたか優しく生徒に伝えてください。
"""

# ==========================================
# 4.5 テーマ（ライト/ダーク）切り替えの準備
#     ※Streamlitには実行中テーマ変更の公式APIが無いので、
#       config.tomlと同じキーを書き換えて st.rerun() で反映させる
# ==========================================
THEMES = {
    "dark":  {"theme.base": "dark",  "theme.primaryColor": "#4CAF50"},
    "light": {"theme.base": "light", "theme.primaryColor": "#4CAF50"},
}

# 初期テーマ（前回保存した設定を読み込む。無ければダーク）
if "theme" not in st.session_state:
    st.session_state.theme = load_user_theme(st.session_state.user_name)
if "theme_applied" not in st.session_state:
    st.session_state.theme_applied = False

# 今のテーマをStreamlitに適用
for key, value in THEMES[st.session_state.theme].items():
    st._config.set_option(key, value)

# テーマ切り替え中なら、シートに保存（重い処理なのでロード画面が出ている間に1回だけ実行）
if st.session_state.get("switching_theme", False) and not st.session_state.theme_applied:
    save_user_theme(st.session_state.user_name, st.session_state.theme)

# 切り替え直後だけ、もう1回だけ再描画して確実に反映させる
if not st.session_state.theme_applied:
    st.session_state.theme_applied = True
    st.rerun()

# ==========================================
# 5. サイドバー：モデル選択（先に描画が必要な部分だけ）
# ==========================================
with st.sidebar:
    st.subheader("設定")
    model_option = st.selectbox(
        "使うAIモデルを選択：",
        ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.5-flash"),
        key="model_selector",
    )

    new_theme = st.radio(
        "ディスプレイモード",
        options=["light", "dark"],
        format_func=lambda x: " ライト" if x == "light" else " ダーク",
        index=0 if st.session_state.theme == "light" else 1,
    )
    if new_theme != st.session_state.theme:
        st.session_state.theme = new_theme
        st.session_state.theme_applied = False    # 再適用フラグ
        st.session_state.switching_theme = True   # ロード画面を出す合図（保存は次の描画で行う）
        st.rerun()


# ==========================================
# 6. チャット履歴データの初期化（アプリ起動後、最初の1回だけ）
#    ※ サイドバーの履歴一覧より先に実行することで、
#      ログイン直後の最初の画面からちゃんと一覧が表示される
# ==========================================
if "chat_history" not in st.session_state:
    restored = load_user_history_from_sheet(st.session_state.user_name, client, sys_instruct, model_option)

    if restored:
        # シートに過去ログがあった → それを復元する
        st.session_state.chat_history = restored
        st.session_state.current_chat = list(restored.keys())[-1]
    else:
        # 過去ログが無かった（初めてのユーザー） → 新しく最初のチャットを作る
        initial_session = client.chats.create(
            model=model_option,
            config=types.GenerateContentConfig(
                system_instruction=sys_instruct,
                temperature=0.7,
            ),
        )
        st.session_state.chat_history = {
            "最初の冒険": {
                "messages": [
                    {"role": "assistant", "content": "ハァン... 僕の部屋へようこそ|-,-| MOD開発を手伝うよ、ホォン↓"}
                ],
                "session": initial_session,
            }
        }
        st.session_state.current_chat = "最初の冒険"

# モデルが切り替えられたら、今表示中のチャットのセッションだけ作り直す
if "current_model" not in st.session_state:
    st.session_state.current_model = model_option

if st.session_state.current_model != model_option:
    st.session_state.chat_history[st.session_state.current_chat]["session"] = client.chats.create(
        model=model_option,
        config=types.GenerateContentConfig(
            system_instruction=sys_instruct,
            temperature=0.7,
        ),
    )
    st.session_state.current_model = model_option

# 今表示中のチャットのデータを取り出す
current_chat_data = st.session_state.chat_history[st.session_state.current_chat]
messages = current_chat_data["messages"]
chat_session = current_chat_data["session"]


# ==========================================
# 7. サイドバー：新規チャット ＋ チャット履歴一覧
#    （chat_history の初期化が終わった後に表示する）
# ==========================================
with st.sidebar:
    st.divider()

    if st.button("＋ 新しいチャットを開始", use_container_width=True):
        existing = st.session_state.get("chat_history", {})
        new_key = f"新しい冒険 {len(existing) + 1}"
        new_session = client.chats.create(
            model=model_option,
            config=types.GenerateContentConfig(
                system_instruction=sys_instruct,
                temperature=0.7,
            ),
        )
        st.session_state.chat_history[new_key] = {
            "messages": [],
            "session": new_session,
        }
        st.session_state.current_chat = new_key
        st.rerun()

    st.divider()
    st.subheader("チャット履歴")

    # 選択中のチャットだけ、ボタンの枠を緑色にするCSS
    # （keyを付けたボタンには .st-key-<key> クラスが自動で付くので、それを狙い撃ち）
    chat_titles = list(st.session_state.chat_history.keys())
    selected_idx = chat_titles.index(st.session_state.current_chat)
    st.markdown(
        f"""
        <style>
        .st-key-select_{selected_idx} button {{
            border: 2px solid #4CAF50 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    for idx, title in enumerate(chat_titles):
        chat_id = f"chat_{title}"

        with st.container():
            col1, col2, col3 = st.columns([0.6, 0.2, 0.2])

            # 📍は付けず、タイトルだけ表示（選択中は上のCSSで緑枠になる）
            if col1.button(title, key=f"select_{idx}", use_container_width=True):
                st.session_state.current_chat = title
                st.rerun()

            if col2.button("✏️", key=f"rename_{chat_id}"):
                st.session_state[f"renaming_{title}"] = True
                st.rerun()

            if col3.button("🗑️", key=f"del_{chat_id}"):
                if len(st.session_state.chat_history) > 1:
                    with st.spinner("削除中..."):
                        delete_chat_from_sheet(st.session_state.user_name, title)
                    del st.session_state.chat_history[title]
                    if st.session_state.current_chat == title:
                        st.session_state.current_chat = list(st.session_state.chat_history.keys())[0]
                    st.rerun()

        if st.session_state.get(f"renaming_{title}", False):
            new_name = st.text_input("新しい名前", key=f"input_{title}")
            if st.button("決定", key=f"confirm_{title}"):
                if new_name and new_name not in st.session_state.chat_history:
                    with st.spinner("名前を変更中..."):
                        rename_chat_in_sheet(st.session_state.user_name, title, new_name)
                    st.session_state.chat_history[new_name] = st.session_state.chat_history.pop(title)
                    if st.session_state.current_chat == title:
                        st.session_state.current_chat = new_name
                st.session_state[f"renaming_{title}"] = False
                st.rerun()


# ==========================================
# 8. 画面の見た目（UI）の設定
# ==========================================

col1, col2, col3 = st.columns([1, 1, 1])
with col2:
    st.image("images/wood house.png", width=200)

st.markdown("<h1 style='text-align: center;'> Unemployed Villager </h1>", unsafe_allow_html=True)


# 画面右上に日本時間を表示（時・分のみ。タイトルと同じMinecraftフォント＆白文字＋黒縁取り）
@st.fragment(run_every="10s")
def show_jst_clock():
    jst = datetime.timezone(datetime.timedelta(hours=9))  # 日本は常にUTC+9（夏時間なし）
    now = datetime.datetime.now(jst)
    st.markdown(
        f"""
        <div style="
            position: fixed;
            top: 25px;
            right: 50px;
            z-index: 1000;
            font-family: 'MinecraftFont', sans-serif;
            color: #FFFFFF;
            text-shadow: 2px 2px 0 #000, -2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000;
            font-size: 48px;
        ">{now:%H:%M}</div>
        """,
        unsafe_allow_html=True,
    )


show_jst_clock()

st.markdown(
    f"""
    <style>
        @font-face {{ font-family: 'MinecraftFont'; src: url("data:font/ttf;base64,{font_base64}"); }}
        h1 {{
            font-family: 'MinecraftFont', sans-serif !important;
            color: #FFFFFF !important;
            text-shadow: 2px 2px 0 #000, -2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000;
            text-align: center;
            padding-bottom: 20px;
        }}
        .stApp {{
            background-image: url("data:image/png;base64,{img_base64}");
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
        }}
        [data-testid="stChatMessage"] {{
            background: url("data:image/png;base64,{textbg_base64}") center/cover !important;
            border: 2px solid #000000 !important;
            border-radius: 8px !important;
            padding: 8px 14px !important;
        }}

         /* 上の白い帯（ヘッダー）を透明にする */
        [data-testid="stHeader"] {{
            background: rgba(0, 0, 0, 0) !important;
        }}

        /*スクロールバーを消す*/
        ::-webkit-scrollbar {{
            display: none;
        }}
        /* Firefox用 */
        * {{
            scrollbar-width: none;
        }}

            
    </style>
    """,
    unsafe_allow_html=True,
)


# ==========================================
# 9. チャット画面の描画
# ==========================================
def display_chat(messages):
    for msg in messages:
        avatar_image = (
            load_image("images/villager.png") if msg["role"] == "assistant"
            else load_image("images/steve.png")
        )
        with st.chat_message(msg["role"], avatar=avatar_image):
            if "<div" in msg["content"] or "<canvas" in msg["content"]:
                st.components.v1.html(msg["content"], height=500, scrolling=True)
            else:
                st.markdown(msg["content"])


display_chat(messages)

# 初期化がすべて終わったので、ロード画面を消す
# 初期化やテーマ切り替えが終わったので、ロード画面を消す
if st.session_state.get("just_logged_in", False) or st.session_state.get("switching_theme", False):
    loading_placeholder.empty()
    st.session_state.just_logged_in = False
    st.session_state.switching_theme = False

# 生徒がメッセージを入力した時の処理
if prompt := st.chat_input("村人に質問する..."):
    # 1. ユーザーのメッセージを保存・即時表示
    messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar=load_image("images/steve.png")):
        st.markdown(prompt)

    # 2. 村人の返答生成
    with st.chat_message("assistant", avatar=load_image("images/villager.png")):
        with st.spinner("無職思考中... "):
            response = chat_session.send_message(prompt)
            response_text = response.text

        if "<div" in response_text or "<canvas" in response_text:
            st.components.v1.html(response_text, height=500, scrolling=True)
        else:
            st.markdown(response_text)

    # 3. 返答を履歴に追加
    messages.append({"role": "assistant", "content": response_text})

    # 4. シートに保存
    try:
        save_log_to_sheet(st.session_state.user_name, st.session_state.current_chat, prompt, response_text)
    except Exception as e:
        st.error(f"ログの保存に失敗したよ...: {e}")

    st.rerun()