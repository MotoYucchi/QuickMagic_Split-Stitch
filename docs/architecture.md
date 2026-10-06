# システムアーキテクチャ設計書

本ドキュメントでは、`Split & Stitch for QuickMagicMotion`（コードネーム: `splitstitch`）のシステム構造、コンポーネント間の責務分担、およびデータフローについて記述します。

---

## 1. 全体データフロー

本システムは、前処理を担当する **Splitter** と、後処理を担当する **Stitcher** の 2 つの独立したモジュール群から構成されます。両者は `session_manifest.json`（セッションマニフェスト）を介して疎結合に連携します。

```text
[ 入力動画 (例: 1080p 60fps) ]
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ Pre-Process: Splitter                                  │
│  1. probe.py: ffprobe による動画特性解析               │
│  2. planner.py: プラン制約と VBV 上界に基づく分割計画  │
│  3. ffmpeg_cmd.py: フレーム正確な切り出しコマンド構築  │
│  4. encoder.py: FFmpeg によるトランスコード実行        │
│  5. verifier.py: チャンク動画のサイズ・フレーム数検証  │
└────────────────────────────────────────────────────────┘
       │
       ├─► chunk_001.mp4, chunk_002.mp4, ... (upload/)
       └─► session_manifest.json
       │
       ▼
══════════════════════════════════════════════════════════
  【外部サービス】QuickMagic による AI モーション推定
  ユーザーがチャンク動画をアップロードし、結果をダウンロード
══════════════════════════════════════════════════════════
       │
       ├─► chunk_001.fbx, chunk_002.fbx, ...
       └─► session_manifest.json
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ Post-Process: Stitcher                                 │
│  1. codecs/: 各フォーマットの解析と MotionClip への変換│
│  2. remap.py: タイムベースの再同期（実時間への復元）   │
│  3. align.py: 重複区間の同一フレーム照合・剛体アライン │
│  4. seam.py: 最小姿勢距離シーム探索・ラグ推定          │
│  5. blend.py: クォータニオン SLERP & 位置線形ブレンド  │
│  6. qc.py: 境界診断メトリクス・レポート生成            │
│  7. codecs/: 結合データの書き戻し                      │
└────────────────────────────────────────────────────────┘
       │
       ▼
[ 結合済みモーションファイル (.fbx / .bvh / .vmd) + QC レポート ]
```

---

## 2. モジュール構成と責務

### 2.1 コアモジュール (`splitstitch.core`)

| モジュール | 責務 | 入力 | 出力 |
| :--- | :--- | :--- | :--- |
| `timebase.py` | 有理数 FPS（`Fraction`）の計算、CFR / VFR タイムラインのマッピング、半開区間ユーティリティ | 文字列・数値 | `TimeBase`, `FrameTimeline` |
| `probe.py` | `ffprobe` を用いた解像度、回転、HDR/色空間、FPS、総フレーム数の抽出 | 動画パス | `ProbeResult` |
| `planner.py` | プラン仕様（`plans.yaml`）と動画仕様に基づく、均等分割・容量上界保証の計算（純粋ロジック） | `ProbeResult`, プラン名 | `PlannerOutput` |
| `ffmpeg_cmd.py` | シェルを経由しない安全な FFmpeg 引数リスト（`trim`, `setpts`, Lanczos スケーリング等）の生成 | `ChunkInfo`, `PlanConfig` | `List[str]` |
| `encoder.py` | FFmpeg プロセスの監視、進捗情報のパース、安全な中断（キャンセル）処理 | 引数リスト | 進捗イベント |
| `verifier.py` | 出力された動画ファイルの容量、`ffprobe` による厳密なフレーム数、SHA-256 の確認 | チャンク動画 | `VerificationResult` |
| `manifest.py` | Pydantic v2 スキーマに基づく `SessionManifest` の検証と JSON シリアライズ | 各種メタデータ | `session_manifest.json` |
| `session.py` | セッション作業ディレクトリの作成および再開（Resume）管理 | 出力先パス | `SessionPaths` |

### 2.2 モーションモジュール (`splitstitch.motion`)

| モジュール | 責務 |
| :--- | :--- |
| `model.py` | フォーマット非依存の共通内部表現（`Skeleton`, `MotionClip`）の定義 |
| `quat.py` | クォータニオンの正規化、半球合わせ（Hemisphere Alignment）、SLERP、オイラー角展開、Yaw 角抽出 |
| `remap.py` | フレームレートの再同期（タイムベース差し替え）、およびサンプリング周波数変換（リサンプリング） |
| `align.py` | 重複区間における同一フレーム同士の姿勢比較に基づく、Yaw 軸回転（円周平均）および水平位置オフセット補正 |
| `seam.py` | 重複区間内の姿勢距離関数、フレーム時間ずれ（ラグ）の推定、最適接合点（シーム）の探索 |
| `blend.py` | イージング曲線（SmoothStep, Linear, Cosine）に基づく回転 SLERP および位置・カーブの線形接合 |
| `qc.py` | 接合境界ごとの角度不連続、Yaw 補正量、移動オフセット、角加速度変化率の診断と HTML/JSON 出力 |
| `stitch.py` | モーションファイルの照合、各クリップの逐次整列、接合、書き出しのオーケストレーション |

### 2.3 コーデック層 (`splitstitch.codecs`)

内部表現である `MotionClip` と各ファイルフォーマットを相互変換する抽象層です。

- `BaseCodec`: 全コーデックが実装する基底インターフェース（`read`, `write`, `capability`）。
- `BVHCodec`: ASCII テキスト形式の Biovision Hierarchy の読み書き。階層構造の解析、オイラー角アンラップ、標準 FPS へのスナップ処理を実装。
- `FBXCodec`: バイナリ FBX の低レベルノード解析と、テンプレート置換方式による書き出し。
- `VMDCodec`: MMD 向けのバイナリレコード解析と、30 fps リサンプリングを伴う書き出し。

---

## 3. 共通内部データ構造 (`MotionClip`)

複数の異なるモーション形式を高精度に接合するため、本システムでは内部で統一したデータ構造 `MotionClip` を使用します。

```python
@dataclass
class Skeleton:
    names: List[str]            # 関節（ボーン）名のリスト (J,)
    parents: np.ndarray         # 親関節インデックス (J,)、ルートは -1
    rest_offsets: np.ndarray    # レストポーズにおけるローカルオフセット (J, 3)
    rotation_orders: List[str]  # オイラー角書き出し用の回転順序 (J,) 例: "XYZ", "ZXY"
    root_index: int = 0         # 移動チャンネルを持つルート関節のインデックス

@dataclass
class MotionClip:
    skeleton: Skeleton
    timebase: TimeBase          # 有理数フレームレート (FPS)
    local_rot: np.ndarray       # ローカル回転クォータニオン (F, J, 4) [x, y, z, w]
    root_pos: np.ndarray        # ルート関節のワールド移動座標 (F, 3) [Y-up, メートル]
    extra_pos: Dict[int, np.ndarray]  # ルート以外の移動チャンネル
    curves: Dict[str, np.ndarray]     # モーフ表情等のスカラーカーブ (F,)
    codec_context: Dict[str, Any]     # テンプレート情報・ヘッダー情報
```

### 設計上の特徴:
1. **クォータニオン内部保持**:
   オイラー角のジンバルロックや周期性（$0^\circ \leftrightarrow 360^\circ$）の問題を避けるため、内部演算はすべて正規化クォータニオンで行われます。
2. **テンプレートコンテキストの保持**:
   FBX などの複雑なフォーマットでは、独自のノード構造やメッシュ情報を破棄せず `codec_context` に保持し、書き戻し時にアニメーションカーブノードのみを差し替える設計となっています。

---

## 4. エラー設計と整合性チェック

本パイプラインは各フェーズで厳格な整合性検証を行います。

1. **プローブ段階**:
   解像度や FPS が取得できない場合、または破損した動画の場合は即座に処理を中断します。
2. **エンコード後段階 (`verifier.py`)**:
   生成された各チャンク動画に対し、`ffprobe` の `nb_read_frames` で実際のフレーム数を取得し、計画フレーム数と 1 フレームでも差異があれば終了コード 5 で停止します。また、プランのファイルサイズ上限を超えた場合も停止します。
3. **モーション結合段階**:
   各チャンクの骨格名および階層構造が一致しているかを確認し、不一致がある場合は処理を行いません。
