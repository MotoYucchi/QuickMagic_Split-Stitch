"""PySide6 Graphical User Interface - Clean, Intuitive, and Accessible Design."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QAction, QColor, QDragEnterEvent, QDropEvent, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from splitstitch.core.encoder import EncodeProgress, run_ffmpeg_encode
from splitstitch.core.ffmpeg_cmd import build_ffmpeg_chunk_cmd
from splitstitch.core.manifest import SessionManifest
from splitstitch.core.planner import PlannerOutput, plan_splitting
from splitstitch.core.probe import ProbeResult, probe_video
from splitstitch.core.session import create_initial_manifest, setup_session_directory
from splitstitch.core.verifier import verify_chunk
from splitstitch.motion.qc import MotionQCReport
from splitstitch.motion.stitch import match_motion_files_to_chunks, stitch_motion_session


# ---------------- Worker Threads ----------------

class SplitWorker(QThread):
    progress_updated = Signal(int, int, str, float)  # cur_frame, total_frames, speed, percent
    chunk_started = Signal(int, int, str)  # chunk_idx, total_chunks, name
    chunk_finished = Signal(int, str, float)  # chunk_idx, name, size_mb
    all_finished = Signal(str)  # output_dir
    failed = Signal(str)

    def __init__(
        self,
        video_path: Path,
        plan_name: str,
        mode: str,
        outdir: Path,
        resolution: str = "auto",
        quality: str = "high",
        overlap_sec: float = 1.0,
    ) -> None:
        super().__init__()
        self.video_path = video_path
        self.plan_name = plan_name
        self.mode = mode
        self.outdir = outdir
        self.resolution = resolution
        self.quality = quality
        self.overlap_sec = overlap_sec
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            probe_res = probe_video(self.video_path)
            planner_out = plan_splitting(
                probe=probe_res,
                plan_name=self.plan_name,
                mode=self.mode,
                resolution_policy=self.resolution,
                quality_preset=self.quality,
                overlap_sec=self.overlap_sec,
            )

            session_paths = setup_session_directory(self.outdir)
            manifest = create_initial_manifest(probe_res, planner_out, session_paths.root_dir.name)

            total_chunks = len(manifest.chunks)

            for idx, chunk in enumerate(manifest.chunks, start=1):
                if self.cancel_event.is_set():
                    return

                chunk_file = session_paths.upload_dir / chunk.filename
                self.chunk_started.emit(idx, total_chunks, chunk.filename)

                cmd = build_ffmpeg_chunk_cmd(
                    probe=probe_res,
                    chunk=chunk,
                    plan_config=manifest.plan,
                    output_path=chunk_file,
                    session_id=manifest.session_id,
                )
                chunk.ffmpeg_args = cmd

                def on_prog(p: EncodeProgress) -> None:
                    self.progress_updated.emit(p.current_frame, p.total_frames, p.speed, p.percent)

                run_ffmpeg_encode(
                    cmd,
                    total_frames=chunk.upload_frame_count,
                    on_progress=on_prog,
                    cancel_event=self.cancel_event,
                )

                # Verify
                v_res = verify_chunk(chunk_file, chunk, 500 * 1000 * 1000)
                if not v_res.is_valid:
                    self.failed.emit(f"チャンク #{idx} の検証に失敗しました: {v_res.error_message}")
                    return

                chunk.status = "verified"
                chunk.size_bytes = v_res.file_size_bytes
                chunk.sha256 = v_res.sha256
                self.chunk_finished.emit(idx, chunk.filename, v_res.file_size_bytes / 1e6)

            manifest.totals.upload_bytes = sum(c.size_bytes for c in manifest.chunks)
            manifest.save(session_paths.manifest_file)
            self.all_finished.emit(str(session_paths.upload_dir))

        except Exception as e:
            self.failed.emit(str(e))


class StitchWorker(QThread):
    progress_updated = Signal(int, int, str)
    all_finished = Signal(MotionQCReport, str)
    failed = Signal(str)

    def __init__(
        self,
        manifest_path: Path,
        motion_files: List[Path],
        output_path: Path,
        fps: Optional[str] = None,
        blend_sec: float = 0.5,
        easing: str = "smoothstep",
        align: str = "yaw+xz",
    ) -> None:
        super().__init__()
        self.manifest_path = manifest_path
        self.motion_files = motion_files
        self.output_path = output_path
        self.fps = fps
        self.blend_sec = blend_sec
        self.easing = easing
        self.align = align

    def run(self) -> None:
        try:
            manifest = SessionManifest.load(self.manifest_path)

            def on_prog(cur: int, total: int, msg: str) -> None:
                self.progress_updated.emit(cur, total, msg)

            report = stitch_motion_session(
                manifest=manifest,
                motion_files=self.motion_files,
                output_path=self.output_path,
                target_fps=self.fps,
                blend_sec=self.blend_sec,
                easing=self.easing,
                align_mode=self.align,
                on_progress=on_prog,
            )
            self.all_finished.emit(report, str(self.output_path))
        except Exception as e:
            self.failed.emit(str(e))


# ---------------- Main Window ----------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Split & Stitch for QuickMagicMotion")
        self.resize(850, 720)
        self.setMinimumSize(750, 600)

        self.loaded_probe: Optional[ProbeResult] = None
        self.split_worker: Optional[SplitWorker] = None
        self.stitch_worker: Optional[StitchWorker] = None

        self._setup_ui()
        self._apply_styling()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Tab widget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # 1. Split Tab
        self.split_tab = QWidget()
        self._build_split_tab(self.split_tab)
        self.tabs.addTab(self.split_tab, "1. 動画分割 (Split)")

        # 2. Stitch Tab
        self.stitch_tab = QWidget()
        self._build_stitch_tab(self.stitch_tab)
        self.tabs.addTab(self.stitch_tab, "2. モーション結合 (Stitch)")

    # ---------------- Split Tab ----------------

    def _build_split_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)
        layout.setSpacing(12)

        # Drop Zone / File Picker
        file_box = QGroupBox("ステップ1: 動画を選択")
        fb_layout = QHBoxLayout(file_box)
        self.split_video_edit = QLineEdit()
        self.split_video_edit.setPlaceholderText("ここに動画ファイルをドラッグ＆ドロップ、または右のボタンから選択")
        self.split_video_edit.setReadOnly(True)
        btn_browse = QPushButton("ファイル選択...")
        btn_browse.clicked.connect(self._browse_split_video)
        fb_layout.addWidget(self.split_video_edit)
        fb_layout.addWidget(btn_browse)
        layout.addWidget(file_box)

        # Video Info Label
        self.video_info_label = QLabel("動画が選択されていません")
        self.video_info_label.setStyleSheet("color: #718096; font-size: 12px; margin-left: 4px;")
        layout.addWidget(self.video_info_label)

        # Plan & Mode Box
        settings_box = QGroupBox("ステップ2: QuickMagic プランと分割モード")
        sb_layout = QVBoxLayout(settings_box)
        sb_layout.setSpacing(10)

        # Plan Selector Row
        plan_row = QHBoxLayout()
        plan_label = QLabel("プラン:")
        plan_label.setFixedWidth(50)
        self.plan_group = QButtonGroup(self)
        self.plan_radios = {}
        plan_row.addWidget(plan_label)
        for p_name in ("Free", "Basic", "Pro", "Max", "Studio"):
            rb = QRadioButton(p_name)
            if p_name == "Free":
                rb.setChecked(True)
            self.plan_group.addButton(rb)
            self.plan_radios[p_name.lower()] = rb
            rb.toggled.connect(self._recalculate_plan_preview)
            plan_row.addWidget(rb)
        plan_row.addStretch()
        sb_layout.addLayout(plan_row)

        # Mode Selector Row
        mode_row = QHBoxLayout()
        mode_label = QLabel("モード:")
        mode_label.setFixedWidth(50)
        self.mode_group = QButtonGroup(self)
        self.rb_stretch = QRadioButton("高精細・全フレーム保持（FPSスケーリング）★推奨")
        self.rb_stretch.setChecked(True)
        self.rb_stretch.setToolTip("全フレームを1枚も捨てずに時間軸を拡張して推定させ、滑らかな動きを復元します。")
        self.rb_stretch.toggled.connect(self._recalculate_plan_preview)

        self.rb_native = QRadioButton("通常モード（プラン上限FPSに合わせる）")
        self.rb_native.setToolTip("プランのFPS上限を超えるフレームは間引かれます。")
        self.rb_native.toggled.connect(self._recalculate_plan_preview)

        self.mode_group.addButton(self.rb_stretch)
        self.mode_group.addButton(self.rb_native)

        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.rb_stretch)
        mode_row.addWidget(self.rb_native)
        mode_row.addStretch()
        sb_layout.addLayout(mode_row)

        layout.addWidget(settings_box)

        # Plan Simulation Card
        self.sim_card = QFrame()
        self.sim_card.setFrameShape(QFrame.StyledPanel)
        self.sim_card.setStyleSheet("background-color: #f7fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px;")
        sim_layout = QVBoxLayout(self.sim_card)
        self.sim_title = QLabel("分割シミュレーション")
        self.sim_title.setStyleSheet("font-weight: bold; color: #2d3748;")
        self.sim_desc = QLabel("動画を選択すると、分割本数と各チャンクの尺・予想容量がここに表示されます。")
        self.sim_desc.setStyleSheet("color: #4a5568;")
        sim_layout.addWidget(self.sim_title)
        sim_layout.addWidget(self.sim_desc)
        layout.addWidget(self.sim_card)

        # Collapsible Advanced Settings
        self.advanced_btn = QPushButton("▼ 詳細設定を表示")
        self.advanced_btn.setFlat(True)
        self.advanced_btn.setStyleSheet("text-align: left; font-size: 12px; color: #4a5568;")
        self.advanced_btn.clicked.connect(self._toggle_advanced_split)
        layout.addWidget(self.advanced_btn)

        self.advanced_widget = QWidget()
        adv_layout = QHBoxLayout(self.advanced_widget)
        adv_layout.setContentsMargins(0, 0, 0, 0)

        # Quality
        adv_layout.addWidget(QLabel("画質:"))
        self.combo_quality = QComboBox()
        self.combo_quality.addItems(["high (CRF 18 / 高品位)", "balanced (CRF 20 / 標準)", "compact (CRF 22 / 軽量)"])
        self.combo_quality.currentIndexChanged.connect(self._recalculate_plan_preview)
        adv_layout.addWidget(self.combo_quality)

        # Resolution
        adv_layout.addWidget(QLabel("解像度:"))
        self.combo_res = QComboBox()
        self.combo_res.addItems(["auto (自動最適化)", "keep (元解像度維持)", "1080 (1080p固定)"])
        self.combo_res.currentIndexChanged.connect(self._recalculate_plan_preview)
        adv_layout.addWidget(self.combo_res)

        # Overlap Sec
        adv_layout.addWidget(QLabel("重なり秒数:"))
        self.spin_overlap = QDoubleSpinBox()
        self.spin_overlap.setRange(0.5, 3.0)
        self.spin_overlap.setValue(1.0)
        self.spin_overlap.setSingleStep(0.2)
        self.spin_overlap.valueChanged.connect(self._recalculate_plan_preview)
        adv_layout.addWidget(self.spin_overlap)

        self.advanced_widget.setVisible(False)
        layout.addWidget(self.advanced_widget)

        # Output Dir
        out_layout = QHBoxLayout()
        out_layout.addWidget(QLabel("出力フォルダ:"))
        self.split_outdir_edit = QLineEdit()
        self.split_outdir_edit.setPlaceholderText("指定しない場合は動画と同じ場所に自動作成されます")
        btn_outdir = QPushButton("参照...")
        btn_outdir.clicked.connect(self._browse_split_outdir)
        out_layout.addWidget(self.split_outdir_edit)
        out_layout.addWidget(btn_outdir)
        layout.addLayout(out_layout)

        # Execute Button
        self.btn_run_split = QPushButton("動画分割を実行")
        self.btn_run_split.setStyleSheet(
            "background-color: #3182ce; color: white; font-weight: bold; padding: 10px; font-size: 14px; border-radius: 6px;"
        )
        self.btn_run_split.clicked.connect(self._run_split)
        layout.addWidget(self.btn_run_split)

        # Progress & Status
        self.split_progress = QProgressBar()
        self.split_progress.setVisible(False)
        layout.addWidget(self.split_progress)

        self.split_status_label = QLabel("")
        layout.addWidget(self.split_status_label)

        layout.addStretch()

    # ---------------- Stitch Tab ----------------

    def _build_stitch_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)
        layout.setSpacing(12)

        # Step 1: Manifest Picker
        m_box = QGroupBox("ステップ1: 分割時の session_manifest.json を選択")
        mb_layout = QHBoxLayout(m_box)
        self.stitch_manifest_edit = QLineEdit()
        self.stitch_manifest_edit.setPlaceholderText("session_manifest.json をドロップまたは選択")
        self.stitch_manifest_edit.setReadOnly(True)
        btn_m = QPushButton("マニフェスト選択...")
        btn_m.clicked.connect(self._browse_manifest)
        mb_layout.addWidget(self.stitch_manifest_edit)
        mb_layout.addWidget(btn_m)
        layout.addWidget(m_box)

        # Step 2: Motion Files Directory
        f_box = QGroupBox("ステップ2: QuickMagic からダウンロードしたモーションフォルダ")
        fb_layout = QHBoxLayout(f_box)
        self.stitch_motion_dir_edit = QLineEdit()
        self.stitch_motion_dir_edit.setPlaceholderText("ダウンロードしたファイル（.fbx, .bvh, .vmd）が入ったフォルダを選択")
        self.stitch_motion_dir_edit.setReadOnly(True)
        btn_f = QPushButton("フォルダ選択...")
        btn_f.clicked.connect(self._browse_motion_dir)
        fb_layout.addWidget(self.stitch_motion_dir_edit)
        fb_layout.addWidget(btn_f)
        layout.addWidget(f_box)

        # Matched files status
        self.stitch_files_status = QLabel("マニフェストとモーションフォルダを選択してください")
        self.stitch_files_status.setStyleSheet("color: #718096; font-size: 12px; margin-left: 4px;")
        layout.addWidget(self.stitch_files_status)

        # Output File Picker
        out_box = QGroupBox("ステップ3: 結合後の出力ファイル")
        ob_layout = QHBoxLayout(out_box)
        self.stitch_output_edit = QLineEdit()
        self.stitch_output_edit.setPlaceholderText("例: Merged_Dance_60fps.fbx")
        btn_save = QPushButton("保存先を選択...")
        btn_save.clicked.connect(self._browse_stitch_output)
        ob_layout.addWidget(self.stitch_output_edit)
        ob_layout.addWidget(btn_save)
        layout.addWidget(out_box)

        # Advanced Settings for Stitching
        self.stitch_adv_btn = QPushButton("▼ 詳細設定を表示")
        self.stitch_adv_btn.setFlat(True)
        self.stitch_adv_btn.setStyleSheet("text-align: left; font-size: 12px; color: #4a5568;")
        self.stitch_adv_btn.clicked.connect(self._toggle_advanced_stitch)
        layout.addWidget(self.stitch_adv_btn)

        self.stitch_adv_widget = QWidget()
        s_adv_layout = QHBoxLayout(self.stitch_adv_widget)
        s_adv_layout.setContentsMargins(0, 0, 0, 0)

        s_adv_layout.addWidget(QLabel("イージング曲線:"))
        self.combo_easing = QComboBox()
        self.combo_easing.addItems(["smoothstep", "linear", "cosine"])
        s_adv_layout.addWidget(self.combo_easing)

        s_adv_layout.addWidget(QLabel("ブレンド時間(秒):"))
        self.spin_blend_sec = QDoubleSpinBox()
        self.spin_blend_sec.setRange(0.2, 2.0)
        self.spin_blend_sec.setValue(0.5)
        self.spin_blend_sec.setSingleStep(0.1)
        s_adv_layout.addWidget(self.spin_blend_sec)

        s_adv_layout.addWidget(QLabel("ルート補正:"))
        self.combo_align = QComboBox()
        self.combo_align.addItems(["yaw+xz (向きと水平移動を補正)", "xz (水平移動のみ)", "none (補正なし)"])
        s_adv_layout.addWidget(self.combo_align)

        self.stitch_adv_widget.setVisible(False)
        layout.addWidget(self.stitch_adv_widget)

        # Execute Button
        self.btn_run_stitch = QPushButton("モーション結合を実行")
        self.btn_run_stitch.setStyleSheet(
            "background-color: #38a169; color: white; font-weight: bold; padding: 10px; font-size: 14px; border-radius: 6px;"
        )
        self.btn_run_stitch.clicked.connect(self._run_stitch)
        layout.addWidget(self.btn_run_stitch)

        # Progress
        self.stitch_progress = QProgressBar()
        self.stitch_progress.setVisible(False)
        layout.addWidget(self.stitch_progress)

        # QC Report Summary Box
        self.qc_summary_label = QLabel("")
        layout.addWidget(self.qc_summary_label)

        layout.addStretch()

    # ---------------- UI Event Handlers ----------------

    def _toggle_advanced_split(self) -> None:
        vis = not self.advanced_widget.isVisible()
        self.advanced_widget.setVisible(vis)
        self.advanced_btn.setText("▲ 詳細設定を隠す" if vis else "▼ 詳細設定を表示")

    def _toggle_advanced_stitch(self) -> None:
        vis = not self.stitch_adv_widget.isVisible()
        self.stitch_adv_widget.setVisible(vis)
        self.stitch_adv_btn.setText("▲ 詳細設定を隠す" if vis else "▼ 詳細設定を表示")

    def _browse_split_video(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "動画ファイルを選択", "", "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;All Files (*)"
        )
        if file_path:
            self.split_video_edit.setText(file_path)
            try:
                self.loaded_probe = probe_video(file_path)
                p = self.loaded_probe
                self.video_info_label.setText(
                    f"解析完了: {p.display_width}x{p.display_height} | {float(p.fps):.2f} fps | "
                    f"計 {p.frame_count} フレーム ({p.duration_sec:.1f} 秒)"
                )
                self.video_info_label.setStyleSheet("color: #2b6cb0; font-size: 12px; margin-left: 4px;")
                self._recalculate_plan_preview()
            except Exception as e:
                QMessageBox.critical(self, "動画解析エラー", f"動画の解析に失敗しました:\n{e}")

    def _browse_split_outdir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "出力先フォルダを選択")
        if d:
            self.split_outdir_edit.setText(d)

    def _recalculate_plan_preview(self) -> None:
        if not self.loaded_probe:
            return

        selected_plan = "free"
        for name, rb in self.plan_radios.items():
            if rb.isChecked():
                selected_plan = name
                break

        mode = "stretch" if self.rb_stretch.isChecked() else "native"
        quality_key = self.combo_quality.currentText().split()[0]
        res_key = self.combo_res.currentText().split()[0]
        overlap = self.spin_overlap.value()

        try:
            out = plan_splitting(
                probe=self.loaded_probe,
                plan_name=selected_plan,
                mode=mode,
                resolution_policy=res_key,
                quality_preset=quality_key,
                overlap_sec=overlap,
            )
            mode_desc = "全フレーム保持（スロー偽装）" if mode == "stretch" else "通常（FPS調整）"
            self.sim_desc.setText(
                f"【{selected_plan.upper()} プラン / {mode_desc}】\n"
                f"・ 分割数: {out.totals.chunk_count} 本\n"
                f"・ 各チャンク尺: 約 {out.chunks[0].upload_duration_sec:.1f} 秒 ({out.chunks[0].upload_frame_count} フレーム)\n"
                f"・ 1チャンク推定容量: 最大 約 {out.estimated_size_per_chunk_mb:.1f} MB (上限内に確実に適合)\n"
                f"・ 消費秒数: 計 {out.totals.upload_seconds:.1f} 秒"
            )
        except Exception as e:
            self.sim_desc.setText(f"計画計算エラー: {e}")

    def _run_split(self) -> None:
        if not self.loaded_probe:
            QMessageBox.warning(self, "注意", "動画ファイルを先に選択してください。")
            return

        video_path = self.loaded_probe.path
        outdir_str = self.split_outdir_edit.text().strip()
        outdir = Path(outdir_str) if outdir_str else video_path.parent

        selected_plan = "free"
        for name, rb in self.plan_radios.items():
            if rb.isChecked():
                selected_plan = name
                break

        mode = "stretch" if self.rb_stretch.isChecked() else "native"
        quality_key = self.combo_quality.currentText().split()[0]
        res_key = self.combo_res.currentText().split()[0]
        overlap = self.spin_overlap.value()

        self.btn_run_split.setEnabled(False)
        self.split_progress.setVisible(True)
        self.split_progress.setValue(0)
        self.split_status_label.setText("分割処理を開始します...")

        self.split_worker = SplitWorker(
            video_path=video_path,
            plan_name=selected_plan,
            mode=mode,
            outdir=outdir,
            resolution=res_key,
            quality=quality_key,
            overlap_sec=overlap,
        )

        self.split_worker.chunk_started.connect(
            lambda idx, total, name: self.split_status_label.setText(f"チャンク #{idx}/{total} ({name}) をエンコード中...")
        )
        self.split_worker.progress_updated.connect(
            lambda cur, tot, spd, pct: self.split_progress.setValue(int(pct))
        )
        self.split_worker.all_finished.connect(self._on_split_finished)
        self.split_worker.failed.connect(self._on_split_failed)
        self.split_worker.start()

    def _on_split_finished(self, out_dir: str) -> None:
        self.btn_run_split.setEnabled(True)
        self.split_progress.setVisible(False)
        self.split_status_label.setText(f"分割が正常に完了しました！ 出力先: {out_dir}")
        QMessageBox.information(
            self,
            "完了",
            f"動画の分割が完了しました！\nQuickMagicへアップロードするファイルは以下に保存されています:\n\n{out_dir}",
        )

    def _on_split_failed(self, error_msg: str) -> None:
        self.btn_run_split.setEnabled(True)
        self.split_progress.setVisible(False)
        self.split_status_label.setText(f"エラー: {error_msg}")
        QMessageBox.critical(self, "分割失敗", f"分割中にエラーが発生しました:\n{error_msg}")

    # ---------------- Stitch Tab Actions ----------------

    def _browse_manifest(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "session_manifest.json を選択", "", "JSON (*.json);;All Files (*)")
        if f:
            self.stitch_manifest_edit.setText(f)
            self._check_stitch_ready()

    def _browse_motion_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "モーションフォルダを選択")
        if d:
            self.stitch_motion_dir_edit.setText(d)
            self._check_stitch_ready()

    def _browse_stitch_output(self) -> None:
        f, _ = QFileDialog.getSaveFileName(
            self, "保存先ファイル", "", "FBX (*.fbx);;BVH (*.bvh);;VMD (*.vmd);;All Files (*)"
        )
        if f:
            self.stitch_output_edit.setText(f)

    def _check_stitch_ready(self) -> None:
        m_str = self.stitch_manifest_edit.text()
        d_str = self.stitch_motion_dir_edit.text()
        if not (m_str and d_str and Path(m_str).is_file() and Path(d_str).is_dir()):
            return

        try:
            manifest = SessionManifest.load(m_str)
            matched = match_motion_files_to_chunks(manifest, d_str)
            self.stitch_files_status.setText(
                f"照合成功: 全 {len(matched)} 本のチャンクモーションが正しく認識されました (形式: {matched[0].suffix})"
            )
            self.stitch_files_status.setStyleSheet("color: #38a169; font-weight: bold; margin-left: 4px;")
            # Auto set default output filename if empty
            if not self.stitch_output_edit.text():
                def_out = Path(d_str).parent / f"Merged_{Path(manifest.source.path).stem}{matched[0].suffix}"
                self.stitch_output_edit.setText(str(def_out))
        except Exception as e:
            self.stitch_files_status.setText(f"ファイル照合エラー: {e}")
            self.stitch_files_status.setStyleSheet("color: #e53e3e; margin-left: 4px;")

    def _run_stitch(self) -> None:
        m_str = self.stitch_manifest_edit.text()
        d_str = self.stitch_motion_dir_edit.text()
        out_str = self.stitch_output_edit.text()

        if not (m_str and d_str and out_str):
            QMessageBox.warning(self, "注意", "マニフェスト、モーションフォルダ、出力先をすべて指定してください。")
            return

        try:
            manifest = SessionManifest.load(m_str)
            matched = match_motion_files_to_chunks(manifest, d_str)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"ファイル確認中にエラーが発生しました:\n{e}")
            return

        easing = self.combo_easing.currentText()
        blend_sec = self.spin_blend_sec.value()
        align_key = self.combo_align.currentText().split()[0]

        self.btn_run_stitch.setEnabled(False)
        self.stitch_progress.setVisible(True)
        self.stitch_progress.setValue(0)
        self.qc_summary_label.setText("モーションの結合処理を実行中...")

        self.stitch_worker = StitchWorker(
            manifest_path=Path(m_str),
            motion_files=matched,
            output_path=Path(out_str),
            blend_sec=blend_sec,
            easing=easing,
            align=align_key,
        )

        self.stitch_worker.progress_updated.connect(
            lambda cur, tot, msg: (
                self.stitch_progress.setValue(int((cur / tot) * 100)),
                self.qc_summary_label.setText(msg),
            )
        )
        self.stitch_worker.all_finished.connect(self._on_stitch_finished)
        self.stitch_worker.failed.connect(self._on_stitch_failed)
        self.stitch_worker.start()

    def _on_stitch_finished(self, report: MotionQCReport, out_path: str) -> None:
        self.btn_run_stitch.setEnabled(True)
        self.stitch_progress.setVisible(False)

        status_text = "良好（ズレなし）" if report.overall_status == "clean" else "注意（一部の継ぎ目に補正適用）"
        self.qc_summary_label.setText(
            f"結合完了: 総尺 {report.total_duration_sec:.2f}秒 ({report.total_frames}フレーム) | 品質: {status_text}"
        )
        self.qc_summary_label.setStyleSheet("color: #38a169; font-weight: bold;")

        QMessageBox.information(
            self,
            "結合完了",
            f"モーションデータの結合が完了しました！\n\n出力ファイル:\n{out_path}\n\n"
            f"総再生時間: {report.total_duration_sec:.2f} 秒\n"
            f"総フレーム数: {report.total_frames}\n"
            f"接合箇所: {report.total_seams} 箇所すべて正常に接合されました。",
        )

    def _on_stitch_failed(self, err_msg: str) -> None:
        self.btn_run_stitch.setEnabled(True)
        self.stitch_progress.setVisible(False)
        self.qc_summary_label.setText(f"エラー: {err_msg}")
        self.qc_summary_label.setStyleSheet("color: #e53e3e;")
        QMessageBox.critical(self, "結合失敗", f"結合処理中にエラーが発生しました:\n{err_msg}")

    def _apply_styling(self) -> None:
        self.setStyleSheet("""
            QMainWindow { background-color: #ffffff; }
            QTabWidget::pane { border: 1px solid #e2e8f0; background: white; border-radius: 6px; }
            QTabBar::tab { background: #edf2f7; color: #4a5568; padding: 10px 24px; font-weight: bold; font-size: 13px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
            QTabBar::tab:selected { background: #ffffff; color: #2b6cb0; border: 1px solid #e2e8f0; border-bottom: none; }
            QGroupBox { font-weight: bold; border: 1px solid #e2e8f0; border-radius: 6px; margin-top: 10px; padding-top: 14px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLineEdit { border: 1px solid #cbd5e0; border-radius: 4px; padding: 6px 10px; }
            QPushButton { border-radius: 4px; padding: 6px 12px; }
        """)
