"""The guideline `load_guideline` returns: how the tools work together, and the
conditions of use. It is the one place for everything that is not specific to a
single tool, per Kari's skill-style MCP contract."""

from __future__ import annotations

SECTIONS: dict[str, str] = {
    "search": """\
## 検索の進め方（search_subsidies）

- keyword は1語で指定します（2〜255文字、スペース不可）。「港区 スタートアップ」のように
  語を並べるとAPIが受け付けません。地域・業種・目的・従業員数は keyword ではなく、
  それぞれの絞り込み引数で指定してください。
- 広い語から始めて、結果を見ながら絞り込みます。目安：「事業」「補助金」→ 分野の語
  （例：創業、起業、スタートアップ、DX、IT導入、研究開発、販路）。表記ゆれ（全角・半角、
  大文字・小文字、カタカナ）はAPI側で吸収されます。
- 同義語を順に試してください。1語で0件でも、別の語で見つかることがよくあります。
- 地域は target_area_search で指定します。都道府県のほか「全国」や地方名も選べます。
  市区町村単位の指定はできません。
- 既定では受付中の補助金だけを返します（acceptance=true）。過去の公募も含めるときは false。
- 結果は既定で20件ずつです。total_count と next_offset を見て、必要なら offset で続きを
  取得してください。""",
    "detail": """\
## 詳細の確認（get_subsidy_detail）

- 有望な候補は get_subsidy_detail で詳細を確認してから回答に含めます。検索結果だけでは
  補助率、対象経費、対象地域の詳細、受付期間の正確な日時が分かりません。
- 上限額（max_amount_yen）が 0 または未設定の場合は、上限が登録されていないことがあります。
  その場合は概要か公募要領で確認してください。
- portal_url は Jグランツのポータルで公式の掲載ページを開くURLです。回答には必ずこのURLを
  添えてください。URLを自分で組み立てないでください。""",
    "attachments": """\
## 添付資料（read_attachment）

- 詳細の attachments に、公募要領（application_guidelines）・交付要綱（outline_of_grant）・
  申請様式（application_form）が一覧されます。
- 対象要件や対象経費を確かめるときは、公募要領を read_attachment で読みます。PDFは
  ページ単位のテキストで返ります。長い資料は next_offset で続きを読んでください。
- PDF以外（Word、Excelなど）は読めません。その場合は portal_url から開くよう案内します。""",
    "coverage": """\
## 収録範囲

- Jグランツに載っているのは、主に国と都道府県の補助金、および一部の市区町村の補助金です。
  市区町村独自の制度の多くは載っていません。
- 市区町村の制度を尋ねられて見つからないときは、Jグランツに無いことを伝え、
  その自治体や産業振興機関の公式サイトで確認するよう案内してください。""",
    "terms": """\
## 利用条件（必ず守ってください）

- 出典表示：取得した情報を回答・公開するときは「出典：Jグランツ（jGrants）」と明記します。
- 情報の扱い：内容は参考情報です。申請前に、公式の掲載ページ（portal_url）で最新情報を
  確認するよう利用者に伝えてください。
- アクセス：同じ検索を短時間に繰り返すなど、APIへの過度な連続アクセスは避けてください。
- 本サーバーはデジタル庁とは関係のない非公式のツールです。""",
}

HEADER = "# Jグランツ ツールの使い方\n"

# Always served whole: an agent that read one section would miss the conditions of use.
GUIDELINE = HEADER + "\n\n".join(SECTIONS.values())
