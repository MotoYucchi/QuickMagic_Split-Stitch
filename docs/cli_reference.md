# CLI コマンドリファレンス

本ドキュメントでは、`splitstitch`（エイリアス: `quickpipeline`）のコマンドラインインターフェースにおける全コマンド、オプション、および終了コードについて記述します。

---

## 1. コマンド一覧

```bash
splitstitch [OPTIONS] COMMAND [ARGS]...
```

| コマンド | 概要 |
| :--- | :--- |
| `probe` | 入力動画の解像度、回転、HDR、フレームレート、総フレーム数を解析 |
| `plan` | 指定プランとパラメータに基づく分割計画を試算（ドライラン） |
| `split` | 動画をプラン制限に合わせて分割・エンコードし、セッションを出力 |
| `verify` | 生成されたチャンク動画の容量、フレーム数、整合性を検証 |
| `stitch` | ダウンロードした複数モーションファイルを単一ファイルに結合（エイリアス: `merge`） |
| `gui` | PySide6 デスクトップ GUI を起動 |

---

## 2. コマンド詳細

### 2.1 `probe`

動画ストリームの仕様を解析し、端末または JSON 形式で出力します。

```bash
splitstitch probe [VIDEO_PATH] [OPTIONS]
```

- **引数**:
  - `VIDEO_PATH` (必須): 解析対象の動画ファイルパス。
- **オプション**:
  - `--json`: 出力を JSON 形式で行います（パイプライン連携用）。
- **使用例**:
  ```bash
  splitstitch probe ./Dance_60fps.mp4
  splitstitch probe ./Dance_60fps.mp4 --json
  ```

---

### 2.2 `plan`

エンコードを実行せず、指定されたプランにおけるチャンク数、フレーム範囲、予想ファイルサイズ、クォータ消費秒数を算出します。

```bash
splitstitch plan [OPTIONS]
```

- **オプション**:
  - `-i, --input PATH` (必須): 元動画ファイルパス。
  - `-p, --plan [free|basic|pro|max|studio]` (既定: `free`): 対象プラン。
  - `-m, --mode [stretch|native]` (既定: `stretch`):
    - `stretch`: 全フレーム保持（時間軸拡張 / FPSスケーリング）。
    - `native`: プランの上限 FPS に合わせてフレーム間引き。
  - `-r, --resolution [auto|keep|1080|1440]` (既定: `auto`):
    - `auto`: 短辺 1080p を保証しつつ、プラン容量に合わせて最適化。
    - `keep`: 元解像度を維持（容量制約によりチャンクが短くなります）。
    - `1080` / `1440`: 短辺のピクセル数を固定。
  - `-q, --quality [high|balanced|compact]` (既定: `high`):
    - `high`: CRF 18 / 高品位ビットレート。
    - `balanced`: CRF 20 / 標準。
    - `compact`: CRF 22 / 軽量。
  - `--overlap-sec FLOAT` (既定: `1.0`): チャンク間の重複秒数（元動画の実時間基準）。
  - `--json`: 計画結果を JSON 形式で出力。
- **使用例**:
  ```bash
  splitstitch plan -i ./Dance_60fps.mp4 --plan free --mode stretch
  ```

---

### 2.3 `split`

分割計画に基づき、FFmpeg による動画切り出し・エンコードを実行し、アップロード用ファイル群とマニフェストを生成します。

```bash
splitstitch split [OPTIONS]
```

- **オプション**:
  - `-i, --input PATH` (必須): 元動画ファイルパス。
  - `-o, --outdir PATH` (必須): セッション出力先ディレクトリ。
  - `-p, --plan` / `-m, --mode` / `-r, --resolution` / `-q, --quality` / `--overlap-sec`: `plan` コマンドと同一。
  - `--resume`: 既にエンコードおよび検証が完了しているチャンクをスキップして再開。
- **使用例**:
  ```bash
  splitstitch split \
    --input ./Dance_60fps.mp4 \
    --outdir ./session_dance/ \
    --plan free \
    --mode stretch \
    --quality high
  ```

---

### 2.4 `verify`

エンコード後の各チャンク動画が、マニフェストに記録された期待フレーム数およびプラン容量上限を満たしているかを検証します。

```bash
splitstitch verify [OPTIONS]
```

- **オプション**:
  - `-s, --session PATH` (必須): セッションディレクトリ、または `session_manifest.json` のパス。
- **使用例**:
  ```bash
  splitstitch verify --session ./session_dance/
  ```

---

### 2.5 `stitch` (エイリアス: `merge`)

QuickMagic からダウンロードした複数のモーションクリップを、元動画の実時間フレームレートに復元しながら 1 本に接合します。

```bash
splitstitch stitch [OPTIONS]
```

- **オプション**:
  - `-m, --manifest PATH` (必須): `session_manifest.json` のパス。
  - `-d, --motion-dir PATH` (必須): ダウンロードしたモーションファイルが格納されているフォルダ。
  - `-o, --output PATH` (必須): 結合後の出力ファイルパス（`.fbx`, `.bvh`, `.vmd`）。
  - `--fps TEXT`: 出力フレームレート（既定: 元動画のフレームレートを自動復元）。
  - `--blend-sec FLOAT` (既定: `0.5`): 接合窓のブレンド秒数（実時間基準）。
  - `--easing [smoothstep|linear|cosine]` (既定: `smoothstep`): 接合時のイージング関数。
  - `--align [yaw+xz|xz|none]` (既定: `yaw+xz`):
    - `yaw+xz`: 重複区間から Yaw 回転と水平移動オフセットを推定して補正。
    - `xz`: 水平移動のみ補正。
    - `none`: 座標変換を行わない。
  - `--vertical [keep|align]` (既定: `keep`):
    - `keep`: 元の接地高さを維持。
    - `align`: 垂直方向（Y 軸）の段差も一致させる。
  - `--seam [auto|center]` (既定: `auto`):
    - `auto`: ガード区間を除外したコア領域内で、姿勢不連続が最小の点を探索。
    - `center`: 重複区間の中央で固定接合。
  - `--report PATH`: 結合品質レポートの出力先パス（`.html` または `.json`）。
- **使用例**:
  ```bash
  splitstitch stitch \
    --manifest ./session_dance/session_manifest.json \
    --motion-dir ./downloaded/ \
    --output ./final_motions/Dance_Merged_60fps.fbx \
    --report ./final_motions/qc_report.html
  ```

---

## 3. 終了コード (Exit Codes)

スクリプトや CI での自動判定に使用できる終了コード体系です。

| コード | 意味 | 対処 |
| :---: | :--- | :--- |
| `0` | 正常終了 | 処理成功。 |
| `1` | 一般エラー | ログメッセージを確認してください。 |
| `2` | コマンドライン引数不正 | オプション指定を確認してください。 |
| `3` | 入力動画エラー | 動画ファイルが存在しない、または破損しています。 |
| `4` | 計画計算エラー | 指定された制約を満たす分割計画が作れませんでした。 |
| `5` | エンコード / 検証失敗 | フレーム数の不一致、またはファイルサイズ超過が発生しました。 |
| `7` | モーション結合エラー | 骨格の不一致、またはモーションファイル数の不足です。 |
