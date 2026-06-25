import streamlit as st
import base64
from google import genai
from google.genai import types
from PIL import Image

def load_image(path):
    try:
        return Image.open(path)
    except:
        return "👦" # 画像がない時の保険

def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

def get_base64_of_font(font_file):
    with open(font_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

# フォントファイルをBase64に変換
font_base64 = get_base64_of_font("fonts/MinecraftTen-VGORe.ttf")

# background.png を変換！
img_base64 = get_base64_of_bin_file("images/background.png")
    
# 履歴を管理するデータ構造
if "chat_history" not in st.session_state:
    # { "タイトル": [メッセージリスト] } の形式
    st.session_state.chat_history = {
        "最初の冒険": [{"role": "assistant", "content": "ハァン... 村人の館へようこそ！"}]
    }

# 今どのチャットを開いているか
if "current_chat" not in st.session_state:
    st.session_state.current_chat = "最初の冒険"

# 返答を受け取った後に…
if len(st.session_state.chat_history[st.session_state.current_chat]) == 2:
    # 最初のやり取りが終わったらGeminiにタイトルをお願いする
    title_prompt = f"このチャット内容を30文字以内で要約してタイトルを付けて: {prompt}"
    new_title = client.chats.create(model="gemini-1.5-flash").send_message(title_prompt).text
    
    # 辞書のキーを書き換えて、履歴を移動させる
    st.session_state.chat_history[new_title] = st.session_state.chat_history.pop(st.session_state.current_chat)
    st.session_state.current_chat = new_title
    st.rerun()

with st.sidebar:
    
    # 1. 新しいチャットを作成するボタン
    if st.button("＋ 新しいチャットを開始", use_container_width=True):
        new_key = f"新しい冒険 {len(st.session_state.chat_history) + 1}"
        st.session_state.chat_history[new_key] = []
        st.session_state.current_chat = new_key
        st.rerun()
    
    st.divider()

    st.subheader("チャット履歴")
    
    # 2. 履歴の表示と切り替え
    for title in list(st.session_state.chat_history.keys()):
        # 自分の現在のチャットには目印をつける（ユーザー体験向上！）
        btn_label = f"📍 {title}" if title == st.session_state.current_chat else title
        
        with st.container():
            col1, col2, col3 = st.columns([0.6, 0.2, 0.2])
            
            # チャット切り替えボタン
            if col1.button(btn_label, key=f"select_{title}", use_container_width=True):
                st.session_state.current_chat = title
                st.rerun()
            
            # 鉛筆（名前変更）とゴミ箱（削除）
            if col2.button("✏️", key=f"rename_{title}"):
                st.session_state[f"renaming_{title}"] = True
                st.rerun()
                
            if col3.button("🗑️ ", key=f"del_{title}"):
                if len(st.session_state.chat_history) > 1:
                    del st.session_state.chat_history[title]
                    st.session_state.current_chat = list(st.session_state.chat_history.keys())[0]
                    st.rerun()

        # 名前変更処理
        if st.session_state.get(f"renaming_{title}", False):
            new_name = st.text_input("新しい名前", key=f"input_{title}")
            if st.button("決定", key=f"confirm_{title}"):
                st.session_state.chat_history[new_name] = st.session_state.chat_history.pop(title)
                st.session_state.current_chat = new_name
                st.session_state[f"renaming_{title}"] = False
                st.rerun()


# ==========================================
# 1. APIキーの設定（エンジンを起動する鍵）
# ==========================================
API_KEY = st.secrets["GEMINI_API_KEY"]
client = genai.Client(api_key=API_KEY)

if "client" not in st.session_state:
    st.session_state.client = genai.Client(api_key=API_KEY)

client = st.session_state.client

# ==========================================
# 2. 村人の「裏設定」と「記憶」の準備
# ==========================================
# 生徒には見えないシステムプロンプト（状態の固定）
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
※使用する


## 【ステップ1：モックカードをそれぞれキャンバス機能で生成する】


生徒からアイデアをもらったら、そのアイデアの実装に必要なコードを分析・把握し、モックカードをキャンバスで生成してください。一回の依頼につき、一枚のモックカードを生成してください。

# HTML/CSS MOC Card Generation Rules
Do not use image generation tools for card creation. Instead, generate a functional "MOC Card" preview using HTML and CSS within the Canvas workspace.
Constraint: Use only HTML <div> tags and inline CSS style attributes for generating mock cards. The use of <canvas> elements and JavaScript is strictly prohibited. This is to ensure compatibility and consistent rendering within the application.

- **Role:** Act as a front-end developer to generate a visual preview of an MOC Card based on student requests.

- **Interactive Editing:**
    1. Upon student feedback (e.g., "Change the title color," "Increase font size"), modify the corresponding CSS or HTML and update the Canvas preview.
    2. Maintain structural integrity (Header, Variable Area, Main Box, Footer Banner) during all modifications.
- **Technical Specifications:**
    - Use **CSS Flexbox or Grid** for a responsive layout.
    - Use `border`, `background-color`, and `padding` properties to define card components (blue/red borders, colored title/footer banners).
    - Ensure all card text is rendered in Japanese as requested by the student's code logic.
    - Keep the design flat (no 3D effects, shadows, or gradients).


⚠️ [Rules for Forced Activation of the Image Generation Tool] - It is strictly forbidden to represent cards in the chat window using text, text codes or bullet points (Markdown). - **Your role in Step 2 is *solely* to invoke the built-in image generation tool, generate a ‘mock card image (illustration)’ based on the conditions below and the attached knowledge, and output it to the chat screen. Please do not generate anything other than method cards (such as explanatory slides and image sources). 



## Common Design Principles

Style: Flat design. 3D effects, diagonal angles, and gradients are strictly prohibited.

Card Shape: Rectangular. White background.

Perspective: Front view (the camera must be facing the card directly).

## 🟦 Method Card Specifications

Outer Border: Thin, vivid blue border.

Title Area: A "vivid blue horizontal rectangle" in the top-left corner. Write the method name (e.g., "When ... is clicked") in white text inside.

Variable Area: Place the word "変数" (Variables) in small black text below the title. Directly beneath, place a "white rectangular box with a thin blue border" containing only the Data-types in black text.

Central Method Box: A "large, thin-blue-bordered white rectangular box" in the center.

Method Code: Write the Java method code (full body of method) inside.
※CRITICAL LAYOUT CONSTRAINT: The text must strictly fit inside the red border. Ensure the text is word-wrapped (multi-line) and the font size is scaled down appropriately. Absolutely NO text should overflow or touch the borders. Leave clear padding (margins) between the text and the red border.


Action Insertion Area: Place a "bright red rectangle" in the center of the box, containing the white text: "ここにはアクションが入るよ！" (Action goes here!).

Return Statement: Write the return statement below the red box in black text.

Footer Banner: A solid purple horizontal band at the very bottom. Write "説明: [Description text]" in white text.

## 🟥 Action Card Specifications

Outer Border: Thin, vivid red border.

Title Area: A "vivid red horizontal rectangle" in the top-left corner. Write the action name (e.g., "Do ...") in white text inside.

Variable Area: Place the word "変数" (Variables) in small black text below the title. Directly beneath, place a "white rectangular box with a thin red border" containing only the Data-types in black text.

Central Action Box: A "large, thin-red-bordered white rectangular box" in the center.

Write the full Java code for the action in black text inside the box.
※CRITICAL LAYOUT CONSTRAINT: The text must strictly fit inside the red border. Ensure the text is word-wrapped (multi-line) and the font size is scaled down appropriately. Absolutely NO text should overflow or touch the borders. Leave clear padding (margins) between the text and the red border.

Footer Banner: A solid brown horizontal band at the very bottom. Write "ヒント: [Hint text]" in white text.

## ⚠️ Strict Requirements for Generation

Do not confuse Method Cards with Action Cards.

Do not generate any background environment; generate only the white-background card.

Do not include card numbers (e.g., 01, 02).

Ensure all text is written correctly in Japanese.


##【ステップ2：コードを生成する】

メソッドカードとアクションカードの生成が終了し、生徒から「コードを見せて！」と言われたら、生成したモックカード内で使用したコードのみ、正しく使用できるように組み合わせてコードをコピーペーストできるように生成してください。インポートや継承、クラスの生成などのメソッドカードとアクションカードに記載されていないコードは絶対に生成しないでください。


# アニメや漫画などの再現リクエストへの対応ルール


- 生徒から実在するアニメ、漫画、ゲームなどのキャラクター（モブ）やアイテムを再現したいと言われたら、そのまま全てを再現しようとせず、そのキャラクターやアイテムの「最も特徴的な1つの能力やエフェクト」に絞ってください。


- （例：「五条悟」なら「相手を無限に足止めする（移動速度低下ポーション効果）」、「爆豪勝己」なら「攻撃した場所を爆発させる」など、既存のマイクラの機能（ポーション、爆発、雷、テレポート、飛行など）に落とし込みます。）


- コードを出す前に、村人の口調で「〇〇のあのカッコいい能力だねぇ！今回は一番特徴的な『〜〜する機能』をコードにしてみたよ、ホォ～ン↴」と、どの能力を再現したかを優しく生徒に伝えてください。

"""

# 会話の履歴（セッション）を保持する仕組み
if "chat_session" not in st.session_state:
    # テンポよく会話するためにFlashモデルを採用
    st.session_state.chat_session = client.chats.create(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=sys_instruct,
            temperature=0.7, # 少しランダム性を持たせる
        )
    )

# 画面に表示する用のメッセージ履歴
if "messages" not in st.session_state:
    # 最初の一言
    st.session_state.messages = [{"role": "assistant", "content": "ハァン... 無職だけど、君のMOD製作を手伝うホォン↑ここにアイデアを書き込んでごらん？"}]


# ==========================================
# 3. 画面の見た目（UI）の設定
# ==========================================

# 1. 3列のレイアウトを作る（左右を余白にして、真ん中にアイコンを置く）
col1, col2, col3 = st.columns([1, 1, 1])

# 2. 真ん中の列(col2)にアイコンを表示
with col2:
    # 画像のパスを指定して、サイズを調整（widthで大きくできる！）
    st.image("images/wood house.png", width=200)

# 3. その下にタイトルを表示（中央寄せ）
st.markdown("<h1 style='text-align: center;'> Umemployed Villager </h1>", unsafe_allow_html=True)

st.markdown(f"""
<style>
    /* 1. フォントを登録する */
    @font-face {{
        font-family: 'MinecraftFont';
        src: url("data:font/ttf;base64,{font_base64}");
    }}

    /* 2. タイトル(h1)に適用 */
    h1 {{
        font-family: 'MinecraftFont', sans-serif !important;
        color: #FFFFFF;
        letter-spacing: 2px;
    }}
    
</style>
""", unsafe_allow_html=True)


st.markdown(f"""
<style>
    /* タイトルの見た目をマイクラ風にカスタマイズ */
    h1 {{
        font-family: 'MinecraftFont', sans-serif !important;
        color: #FFFFFF !important;      /* 文字色を「白」にする */
        text-shadow: 
            2px 2px 0 #000, 
            -2px -2px 0 #000, 
            2px -2px 0 #000, 
            -2px 2px 0 #000;          /* 文字の周りにくっきりした影（縁取り） 
        text-align: center;
        padding-bottom: 20px;
    }}
            
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<style>
    .stApp {{
        background-image: url("data:image/png;base64,{img_base64}");
        background-size: cover;          /* 画面いっぱいに広げる */
        background-position: center;     /* 画像を中央に寄せる */
        background-attachment: fixed;    /* スクロールしても背景を固定する */
    }}
    
    /* チャット枠は少しだけ透明度を上げて、背景の洞窟をチラ見せしよう */
    [data-testid="stChatMessage"] {{
        background-color: rgba(255, 255, 255, 0.7); 
        border: 2px solid #000000;
        border-radius: 10px;
    }}
</style>
""", unsafe_allow_html=True)


# サイドバーにモデル選択を追加
with st.sidebar:
    st.subheader("設定")
    
    model_option = st.selectbox(
        "使うAIモデルを選択：",
        ("gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.5-flash"),
        index=0 # 最初は1.5-flashにしておくのが無難だねぇ
    )
    
    

# 3. 村人の「裏設定」と「記憶」の準備 の中にあるセッション作成をこう変える
if "chat_session" not in st.session_state:
    # 選択したモデルをここで使う！
    st.session_state.chat_session = client.chats.create(
        model=model_option,  # ← ここをサイドバーの値にする
        config=types.GenerateContentConfig(
            system_instruction=sys_instruct,
            temperature=0.7,
        )
    )


# ==========================================
# 4. チャット画面の描画
# ==========================================
# 過去の会話をすべて表示するループ（ここを直してねぇ！）
for msg in st.session_state.messages:
    # 役割によってアイコンを出し分ける
    avatar_image = load_image("images/villager.png") if msg["role"] == "assistant" else load_image("images/steve.png")
    
    with st.chat_message(msg["role"], avatar=avatar_image):
        if "<div" in msg["content"] or "<canvas" in msg["content"]:
            st.components.v1.html(msg["content"], height=500, scrolling=True)
        else:
            st.markdown(msg["content"])

# 生徒がメッセージを入力した時の処理
if prompt := st.chat_input("村人に質問する..."):
    # 1. 生徒のメッセージ表示＆保存
    with st.chat_message("user", avatar = load_image("images/steve.png")):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    

    # 2. 村人の返答
    with st.chat_message("assistant", avatar = load_image("images/villager.png")):
        response = st.session_state.chat_session.send_message(prompt)
        response_text = response.text
        
        # 【重要】HTMLタグが含まれている時はHTMLのみ表示、それ以外はMarkdownのみ表示
        if "<div" in response_text or "<canvas" in response_text:
            st.components.v1.html(response_text, height=500, scrolling=True)
        else:
            st.markdown(response_text)
            
    # 3. 履歴に保存＆リラン
    st.session_state.messages.append({"role": "assistant", "content": response_text})
    st.rerun()