# セッションマニフェスト仕様書 (`session_manifest.json`)

本ドキュメントでは、前処理（Splitter）と後処理（Stitcher）のデータ受け渡しに使用される `session_manifest.json` のスキーマ定義と各フィールドの意味を記述します。

---

## 1. 概要と設計原則

1. **唯一の真実としてのソースフレーム番号**:
   チャンクの区間管理は「秒」ではなく「元動画の 0 始まりフレームインデックス」を基準とします。これにより、浮動小数点数の丸め誤差による 1 フレームのズレ（オフバイワンエラー）を構造的に排除します。
2. **半開区間 `[start, end)` の採用**:
   開始フレームを含み、終了フレームを含まない半開区間を採用しています。区間の長さは常に `end - start` となり、隣接チャンクとの境界計算が明確になります。
3. **有理数表記によるタイムベース保持**:
   FPS やスケーリング比率は `"60/1"` や `"60000/1001"` のような分数形式の文字列として記録し、浮動小数点数の丸め誤差を排除します。

---

## 2. ディレクトリ構成

分割処理を実行すると、指定された出力先フォルダ内に以下の構成が生成されます。

```text
session_directory/
├── session_manifest.json   # 本仕様書で定義されるマニフェストファイル
├── upload/                 # QuickMagic にアップロードする動画チャンク群
│   ├── chunk_001of003.mp4
│   ├── chunk_002of003.mp4
│   └── chunk_003of003.mp4
├── logs/                   # FFmpeg のエンコードログ
└── preview/                # 将来拡張用のサムネイル等
```

---

## 3. JSON スキーマ詳細

以下は `session_manifest.json` の完全なサンプルです。

```json
{
  "schema_version": 1,
  "tool": {
    "name": "splitstitch",
    "version": "0.1.0",
    "ffmpeg_version": "7.0.2"
  },
  "session_id": "qm_20261007_014809_af9df5",
  "created_at": "2026-10-07T01:48:09.123456+00:00",
  "source": {
    "path": "/path/to/Dance_4K_60fps.mov",
    "size_bytes": 1824551232,
    "fingerprint": null,
    "width": 3840,
    "height": 2160,
    "rotation": 0,
    "fps": "60/1",
    "vfr": false,
    "frame_count": 3600,
    "first_frame_pts_sec": 0.0,
    "color": {
      "transfer": "bt709",
      "hdr": false,
      "pix_fmt": "yuv420p"
    }
  },
  "plan": {
    "name": "free",
    "mode": "stretch",
    "declared_fps": "30/1",
    "stretch_ratio": "2/1",
    "resolution_policy": "auto",
    "output_resolution": [1920, 1080],
    "quality_preset": "high",
    "encode": {
      "codec": "libx264",
      "crf": 18,
      "maxrate_kbps": 12000,
      "bufsize_kbps": 12000,
      "preset": "slow"
    }
  },
  "overlap": {
    "source_frames": 60,
    "guard_upload_frames": 8,
    "blend_source_frames": 30
  },
  "chunks": [
    {
      "index": 1,
      "filename": "chunk_001of005.mp4",
      "source_frame_range": [0, 768],
      "upload_frame_count": 768,
      "upload_duration_sec": 25.6,
      "size_bytes": 38211044,
      "sha256": "c41d8e...39f",
      "ffmpeg_args": ["ffmpeg", "-hide_banner", "..."],
      "status": "verified"
    },
    {
      "index": 2,
      "filename": "chunk_002of005.mp4",
      "source_frame_range": [708, 1476],
      "upload_frame_count": 768,
      "upload_duration_sec": 25.6,
      "size_bytes": 37902117,
      "sha256": "a87e21...01b",
      "ffmpeg_args": ["ffmpeg", "-hide_banner", "..."],
      "status": "verified"
    }
  ],
  "totals": {
    "chunk_count": 5,
    "upload_seconds": 128.0,
    "upload_bytes": 190331220
  },
  "qc_summary": null
}
```

---

## 4. フィールド定義

### 4.1 `source` ブロック（入力動画メタデータ）
- `width`, `height`: 動画ストリームの幅と高さ（ピクセル）。
- `rotation`: メタデータに記録された回転角度（0, 90, 180, 270）。表示解像度の判定に使用されます。
- `fps`: 有理数文字列形式（例: `"60/1"`, `"60000/1001"`）。
- `vfr`: 可変フレームレート（Variable Frame Rate）フラグ。
- `frame_count`: パケット単位またはフレーム単位で確認された総フレーム数。
- `first_frame_pts_sec`: 最初の映像フレームのプレゼンテーションタイムスタンプ（秒）。

### 4.2 `plan` ブロック（分割計画パラメータ）
- `name`: 選択されたプラン（`"free"`, `"basic"`, `"pro"`, `"max"`, `"studio"`）。
- `mode`: `"stretch"`（時間軸拡張・全フレーム保持）または `"native"`（プラン上限FPSに合わせる）。
- `declared_fps`: 生成されたチャンク動画の宣言フレームレート（例: `"30/1"`）。
- `stretch_ratio`: 時間軸の拡張比率（$\text{source.fps} / \text{declared\_fps}$）。結合時の時間再同期に使用されます。
- `output_resolution`: チャンク動画の出力解像度 `[幅, 高さ]`。

### 4.3 `overlap` ブロック（接合パラメータ）
- `source_frames`: チャンク間の重複区間の長さ（元動画のフレーム数）。
- `guard_upload_frames`: AI 推定器の時間的文脈不足による端部誤差（エッジ効果）を除外するためのガードフレーム数（既定 8）。
- `blend_source_frames`: 接合時に SLERP 補間を行う窓幅（元動画のフレーム数）。

### 4.4 `chunks` 配列（各チャンクの情報）
- `source_frame_range`: 元動画における半開区間 `[開始フレーム, 終了フレーム)`。
- `upload_frame_count`: チャンク動画に含まれる総フレーム数（$1:1$ マッピングのため `end - start` と一致）。
- `upload_duration_sec`: アップロード動画の再生時間秒数（$\text{upload\_frame\_count} / \text{declared\_fps}$）。
- `status`: チャンクの状態（`"planned"`, `"encoded"`, `"verified"`, `"failed"`）。
