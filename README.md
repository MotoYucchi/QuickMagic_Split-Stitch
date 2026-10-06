# Split & Stitch for QuickMagicMotion

QuickMagicのプラン制限（解像度・容量・動画尺・FPS）に合わせて入力動画を分割・最適化する前処理（Splitter）と、クラウド推定された複数のモーションデータを高精度に接合・復元する後処理（Stitcher）からなるツールです。

## 主な機能

- **高精細FPSスケーリング（全フレーム保持）**:
  30fps制限のあるプランでも、60fpsや120fpsなどの高フレームレート映像を1フレームも間引かずに時間軸を拡張（スローモーション化）してアップロード。抽出後に元実時間へ再同期し、滑らかなモーションデータを完全復元。
- **フレーム正確な分割**:
  キーフレーム位置に依存せず、有理数タイムベースと半開区間管理に基づき、フレームの重複・欠落をゼロに抑えて均等分割。
- **容量・尺の自動最適化**:
  プランごとの容量上限（VBV上界保証）と解像度要件に適合させ、高品質を維持しながら分割計画を自動算出。
- **剛体アラインとクォータニオン接合**:
  重複区間の同一フレーム同士を比較し、Yaw角・水平移動の自動補正とSLERP補間により、滑らかなモーション接合を実現。
- **直感的なGUIと自動化CLI**:
  動画をドロップしてプランを選ぶだけの操作体系と、パイプライン組み込み可能なCLIを両立。

## インストール

```bash
uv venv
uv pip install -e ".[dev]"
```

## 基本的な使い方 (CLI)

```bash
# 1. 動画解析
splitstitch probe input.mp4

# 2. 分割計画確認（ドライラン）
splitstitch plan --input input.mp4 --plan free --mode stretch

# 3. 分割実行
splitstitch split --input input.mp4 --plan free --mode stretch --outdir ./session01/

# 4. モーション結合
splitstitch stitch --manifest ./session01/session_manifest.json --motion-dir ./motions/ --output output.fbx
```

## GUI の起動

```bash
splitstitch gui
```
