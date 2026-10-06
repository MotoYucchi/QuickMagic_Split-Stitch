# Split & Stitch for QuickMagicMotion

[English](README.md) | [日本語](README.ja.md)

QuickMagic のプラン制限（解像度・容量・動画尺・FPS）に合わせて入力動画を分割・最適化する前処理（**Splitter**）と、推定された複数のモーションデータを接合・復元する後処理（**Stitcher**）を提供するツールです。

---

## 概要と動作原理

QuickMagic は Web 上で利用可能な AI モーションキャプチャサービスですが、契約プラン（Free / Basic / Pro / Max / Studio）ごとにアップロード可能な動画の尺（例: Free は 30 秒）、ファイル容量（例: Free は 50 MB）、および対応フレームレート（Free は 30 fps 固定）に制限が設けられています。

本ツールは以下の 2 つのフェーズにより、長尺動画や高フレームレート動画のモーション抽出を補助します。

1. **Splitter（前処理）**:
   - 入力動画の解像度、フレームレート、総フレーム数を解析します。
   - プランごとの動画尺とファイル容量（ビットレート上限から逆算した VBV 上界）に基づき、均等な長さのチャンク（重複区間を含む）に分割します。
   - **FPSスケーリング（時間軸拡張）モード**: 60 fps や 120 fps などの動画においてフレームの間引きを行わず、フレームレートの宣言値のみを 30 fps（またはプラン受理 FPS）に引き下げてスローモーション動画として出力します（入力 1 フレーム = 出力 1 フレームを維持）。
   - 各チャンクの範囲とパラメータを `session_manifest.json` に記録します。

2. **Stitcher（後処理）**:
   - QuickMagic からダウンロードした各チャンクのモーションデータ（FBX, BVH, VMD）を読み込みます。
   - FPSスケーリングを行ったセッションでは、各キーフレームの時刻・タイムベースを元の実時間フレームレートへ戻します。
   - 重複区間の同一フレーム同士を照合し、骨格の向き（Yaw角の円周平均）および水平位置のオフセットを補正して足滑りやテレポートを抑制します。
   - 推定器の時間境界ノイズ（エッジ効果）を除外した上で、姿勢誤差が最も小さいシーム位置を探索し、球面線形補間（SLERP）および SmoothStep イージングにより 1 本のモーションファイルへ接合します。

---

## 主な機能

- **フレーム単位の正確な切り出し**:
  有理数タイムベース（`Fraction`）と半開区間 `[start, end)` による管理を行い、`trim` フィルタと `setpts=N/(FPS*TB)` によりフレームの重複や欠落を抑えて分割します。
- **容量上限の事前遵守**:
  エンコード後のファイルサイズが契約プランの容量上限を超えないよう、VBV バッファ上限（`-maxrate` / `-bufsize`）を考慮してチャンク最大尺を算出します。
- **剛体アラインメント**:
  チャンクごとのワールド座標原点のリセットに対し、重複区間の同一フレームにおける姿勢を基準にして Yaw 軸回転と水平 XZ 移動を自動調整します。
- **品質レポート出力**:
  接合部ごとの関節角度差、Yaw 補正量、移動オフセット、角加速度変化率を算出し、HTML / JSON 形式で出力します。
- **初心者向けの GUI と自動化向けの CLI**:
  ドラッグ＆ドロップで操作可能な PySide6 GUI と、スクリプトから呼び出し可能な CLI（Typer）の両方を提供します。

---

## 前提条件と環境構築

### 必要な環境

- **Python**: 3.10 以上（3.12 推奨）
- **FFmpeg / ffprobe**: 6.0 以上（7.0 推奨、`PATH` または `~/.local/bin` に配置されていること）
- **OS**: Windows 10/11, macOS 13+, Linux (Ubuntu 22.04+)

### インストール手順

```bash
# リポジトリのクローン
git clone https://github.com/MotoYucchi/QuickMagic_Split-Stitch.git
cd QuickMagic_Split-Stitch

# uv を使用した仮想環境の構築と依存パッケージの導入
uv venv
source .venv/bin/activate  # Windows の場合は .venv\Scripts\activate
uv pip install -e ".[dev]"
```

FFmpeg がインストールされていない場合は、各 OS のパッケージマネージャまたは公式サイトより導入してください。
- Ubuntu: `sudo apt install ffmpeg`
- macOS: `brew install ffmpeg`
- Windows: `winget install Gyan.FFmpeg` または公式静的バイナリの導入

---

## 使い方

### 1. グラフィカルユーザーインターフェース (GUI)

日常的な利用では GUI が便利です。

```bash
splitstitch gui
```

#### 分割（Split タブ）
1. 「動画を選択」に動画ファイルをドラッグ＆ドロップします。
2. 利用する QuickMagic のプラン（Free / Basic / Pro / Max / Studio）を選択します。
3. モードを選択します（全フレーム保持を優先する場合は「高精細・全フレーム保持（FPSスケーリング）」）。
4. シミュレーション表示で分割本数や予想容量を確認します。
5. 「動画分割を実行」をクリックします。完了すると `upload/` フォルダ内に動画チャンク群が出力されます。

#### 結合（Stitch タブ）
1. 分割時に生成された `session_manifest.json` を選択します。
2. QuickMagic からダウンロードしたモーションファイルが入ったフォルダを指定します。
3. 出力先ファイルパス（例: `Merged_Dance_60fps.fbx`）を指定します。
4. 「モーション結合を実行」をクリックします。

---

### 2. コマンドラインインターフェース (CLI)

パイプライン処理やバッチ処理に適しています。

```bash
# 1. 動画ストリームの解析
splitstitch probe input_60fps.mp4

# 2. 分割計画の確認（エンコードなし・ドライラン）
splitstitch plan --input input_60fps.mp4 --plan free --mode stretch

# 3. 分割の実行
splitstitch split \
  --input input_60fps.mp4 \
  --plan free \
  --mode stretch \
  --outdir ./session_dance/

# 4. 生成されたチャンク動画の事前検証
splitstitch verify --session ./session_dance/

# 5. モーションの結合
splitstitch stitch \
  --manifest ./session_dance/session_manifest.json \
  --motion-dir ./downloaded_motions/ \
  --output ./final_motions/Dance_Merged_60fps.bvh \
  --report ./final_motions/qc_report.html
```

---

## 対応フォーマットと実装仕様

| フォーマット | 拡張子 | 実装方式 | タイムベース | 備考 |
| :--- | :--- | :--- | :--- | :--- |
| **BVH** | `.bvh` | 自前パーサー / エクスポーター | 任意（有理数対応） | 階層構造、オイラー角のアンラップ、標準 FPS へのスナップに対応。 |
| **FBX** | `.fbx` | バイナリノード解析 ＋ テンプレート置換 | 任意（KTime 単位） | 第 1 チャンクの FBX を雛形としてアニメーションカーブ（KeyTime / KeyValueFloat）を置換。骨格・メッシュ・独自属性を維持。 |
| **VMD** | `.vmd` | バイナリレコード解析 / 生成 | 最大 60 fps | MMD 公式および互換環境（MMM 等）の 60 fps 表示に対応。60 fps 以下のモーションはそのまま保持し、60 fps を超えるモーション（120 fps 等）は 60 fps へ自動リサンプルされます。モーフ表情に対応。 |

> **注意**: QuickMagic の書き出しプリセットのうち、BIP や C4D 独自形式、iClone 独自形式などは仕様が非公開であるため、直接の結合には対応していません。QuickMagic からは汎用的な FBX または BVH としてエクスポートすることを推奨します。

---

## 制限事項と注意点

1. **時間軸拡張（FPSスケーリング）と推定器の相性**:
   - 動画をスローモーション化（例: 60 fps を 30 fps として 2 倍の尺に引き延ばす）して QuickMagic に入力すると、AI の骨格追従自体は高フレームで抽出できますが、内部で物理演算フィルタ（重力補正や足接地推定）が強く効いている場合、低重力環境のような浮遊感が生じる場合があります。
2. **利用規約に関する留意点**:
   - フレームレート制限のあるプランで時間軸拡張を利用する際は、サービスの利用規約および利用上限ポリシーに従ってください。
3. **被写体の条件**:
   - 本ツールは単一人物の連続テイクを前提としています。複数人が交差する映像や、激しいカメラワーク・大幅なフレームアウトがある映像では、チャンク境界で骨格の取り違えが発生する可能性があります。
4. **VMD のフレームレート仕様（最大 60 fps）**:
   - Vocaloid Motion Data (.vmd) は整数フレーム番号で記録される構造です。MMD 公式および互換ツール（MMM 等）での 60 fps 動作に対応しており、60 fps までのモーション（24, 30, 60 fps 等）はそのまま等倍で記録・出力可能です。60 fps を超えるモーション（120 fps 等）を VMD として出力する場合は、上限である 60 fps へ自動リサンプルされます。120 fps をそのまま維持したい場合は FBX または BVH 形式をご利用ください。

---

## ディレクトリ構造

```text
QuickMagic_Split-Stitch/
├── pyproject.toml              # プロジェクト構成と依存関係定義
├── README.md                   # 英語ドキュメント
├── README.ja.md                # 日本語ドキュメント
├── docs/                       # 詳細ドキュメント
│   ├── design_plan.md          # 開発設計書
│   ├── architecture.md         # システムアーキテクチャ
│   ├── fps_scaling_theory.md   # FPSスケーリングの原理と計算式
│   ├── supported_formats.md    # 対応形式と実装仕様
│   ├── manifest_spec.md        # セッションマニフェスト仕様
│   ├── cli_reference.md        # CLI リファレンス
│   └── troubleshooting.md      # トラブルシューティング
├── src/splitstitch/
│   ├── config/plans.yaml       # QuickMagic 各プランの仕様定義
│   ├── core/                   # 分割・解析・エンコードエンジン
│   ├── motion/                 # 剛体アライン・シーム探索・補間エンジン
│   ├── codecs/                 # 各ファイル形式の入出力実装
│   ├── cli/                    # CLI エントリポイント
│   └── gui/                    # PySide6 GUI 実装
└── tests/                      # 自動テスト群 (単体・性質・E2E)
```

---

## テストの実行

```bash
source .venv/bin/activate
pytest -v
```

Hypothesis による性質ベーステスト、FFmpeg による動画切り出しの実機検証、およびモーションコーデックの往復テストが含まれています。

---

## 作成者 (Author)

- **MotoYucchi** ([GitHub](https://github.com/MotoYucchi))

---

## 免責事項

本ツールはサードパーティ製のオープンソースソフトウェアであり、QuickMagic（並びにその運営会社）とは一切の提携・関係はありません。本ソフトウェアの使用に起因するアカウントの状態や出力結果について、開発者は責任を負いません。
