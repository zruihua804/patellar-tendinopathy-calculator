from __future__ import annotations

from datetime import date, datetime
import hashlib
import hmac

import streamlit as st

from domain import REHAB_PHASES, RETURN_TO_ACTIVITY, TIMEPOINTS, assessment_identity, clinical_warnings, patient_id_from_record, stable_id
from feishu import FeishuAPIError, FeishuBitableClient, FeishuConfig, FeishuConfigurationError
from model import MODEL_VERSION, evidence_scenario_summary, trend_summary
from patient_ocr import OCRUnavailableError, extract_patient_screenshot_data
from questionnaires import (
    VISA_P_ACTIVITY_OPTIONS,
    VISA_P_ITEMS,
    VISA_P_SOURCE_VERSION,
    VISA_P_TRAINING_OPTIONS,
    calculate_visa_p,
    item_score_labels,
    score_from_label,
    training_option_label,
    visa_p_completion_status,
)
from reporting import medical_record_text, patient_report
from storage import DEFAULT_STORAGE, DuplicateRecordError
from voice import parse_rom_dictation
from voice_component import cloud_rom_voice_input


st.set_page_config(page_title="髌腱病临床计算器", page_icon="🦵", layout="wide")


def init_state() -> None:
    defaults: dict[str, object] = {
        "patient_id": "",
        "medical_record_no": "",
        "patient_name": "",
        "sex": "待确认",
        "birth_date": date(1990, 1, 1),
        "consent_status": "待确认",
        "affected_side": "左",
        "episode_status": "新诊断",
        "diagnostic_confidence": "确诊",
        "red_flag_present": False,
        "symptom_duration_weeks": 12,
        "doctor": "",
        "therapist": "",
        "primary_activity": "跳跃/落地",
        "recent_load_change": "未记录",
        "assessment_date": date.today(),
        "timepoint": "基线",
        "source_role": "doctor-assisted",
        "activity_pain_nrs": 3.0,
        "pain_activity_description": "跳跃落地",
        "return_to_activity_status": "未恢复",
        "imaging_summary": "",
        "clinical_notes": "",
        "rom_mode": "主动",
        "knee_flexion_deg": 135.0,
        "knee_extension_deficit_deg": 0.0,
        "rom_pain_or_limit": "",
        "rom_method": "量角器",
        "rehab_week_no": 1,
        "rehab_phase": "症状管理",
        "supervised_sessions": 0,
        "home_training_days": 0,
        "adherence_percent": 0.0,
        "pain_during_load_nrs": 0.0,
        "pain_24h_after_nrs": 0.0,
        "therapist_interpretation": "",
        "baseline_visa_p_total": None,
        "baseline_activity_pain_nrs": None,
        "escalation_or_surgery": "无",
        "escalation_reason": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
    pending_voice_fields = st.session_state.pop("pending_voice_form_fields", None)
    if isinstance(pending_voice_fields, dict):
        for field, value in pending_voice_fields.items():
            st.session_state[field] = value
        st.session_state.voice_apply_success = True


def secret_section(name: str) -> dict[str, object]:
    try:
        return dict(st.secrets.get(name, {}))
    except FileNotFoundError:
        return {}


def require_clinical_access() -> None:
    code = str(secret_section("app").get("clinical_access_code", "")).strip()
    if not code:
        st.sidebar.warning("当前为本地演示模式。接入真实患者资料前，请配置团队访问口令和数据治理。")
        return
    if st.session_state.get("clinical_access_granted"):
        return
    st.title("髌腱病临床工作台")
    st.caption("请输入团队访问口令后再处理真实患者信息。")
    with st.form("clinical_access_form"):
        entered = st.text_input("团队访问口令", type="password")
        submitted = st.form_submit_button("进入临床工作台", type="primary")
    if submitted:
        if hmac.compare_digest(entered, code):
            st.session_state.clinical_access_granted = True
            st.rerun()
        st.error("访问口令不正确。")
    st.stop()


def configured_feishu() -> FeishuConfig | None:
    try:
        return FeishuConfig.from_mapping(secret_section("feishu"))
    except FeishuConfigurationError:
        return None


def render_patient_screenshot_import() -> None:
    st.subheader("患者资料截图识别")
    st.caption("截图只在当前会话内使用本地 OCR 解析；应用不会写入或保存原图。识别结果必须确认后才会填入。")
    uploaded = st.file_uploader("上传患者基本信息截图", type=["png", "jpg", "jpeg"], key="patient_screenshot")
    if uploaded is None:
        return

    image_bytes = uploaded.getvalue()
    fingerprint = hashlib.sha256(image_bytes).hexdigest()
    try:
        with st.spinner("正在本地识别姓名、病历号、性别、年龄和出生日期…"):
            parsed = extract_patient_screenshot_data(image_bytes)
    except OCRUnavailableError as exc:
        st.error(str(exc))
        return
    except Exception:
        st.error("截图识别失败。请上传清晰、完整的患者基本信息区域，或改为手动录入。")
        return

    if st.session_state.get("ocr_fingerprint") != fingerprint:
        st.session_state.ocr_fingerprint = fingerprint
        st.session_state.ocr_review_name = parsed.name
        st.session_state.ocr_review_medical_record_no = parsed.medical_record_no
        st.session_state.ocr_review_sex = parsed.sex
        st.session_state.ocr_review_birth_date = parsed.birth_date or st.session_state.birth_date

    st.success("识别完成，请逐项确认。")
    col1, col2, col3, col4 = st.columns([2, 2, 1, 1.5])
    with col1:
        st.text_input("姓名（确认后填入）", key="ocr_review_name")
    with col2:
        st.text_input("病历号（确认后填入）", key="ocr_review_medical_record_no")
    with col3:
        st.selectbox("性别（确认后填入）", ["女", "男", "待确认"], key="ocr_review_sex")
    with col4:
        st.date_input("出生日期（确认后填入）", key="ocr_review_birth_date")
    with st.expander("查看 OCR 原始文字"):
        st.code("\n".join(parsed.recognized_text) or "未识别到文字")
    if st.button("确认并填入首诊资料", key="apply_patient_screenshot", type="primary"):
        if not st.session_state.ocr_review_name or not st.session_state.ocr_review_medical_record_no:
            st.warning("请先确认姓名和病历号；否则请手动录入。")
        elif st.session_state.ocr_review_sex == "待确认":
            st.warning("请确认性别后再填入。")
        else:
            st.session_state.patient_name = st.session_state.ocr_review_name.strip()
            st.session_state.medical_record_no = st.session_state.ocr_review_medical_record_no.strip()
            st.session_state.sex = st.session_state.ocr_review_sex
            st.session_state.birth_date = st.session_state.ocr_review_birth_date
            st.session_state.patient_id = patient_id_from_record(st.session_state.medical_record_no, st.session_state.patient_name)
            st.success("已填入首诊资料。")


def render_patient_entry() -> None:
    st.subheader("医生首诊速录")
    render_patient_screenshot_import()
    st.divider()
    left, right = st.columns(2)
    with left:
        st.text_input("患者 ID（由病历号自动生成；可确认）", key="patient_id")
        st.text_input("病历号", key="medical_record_no")
        st.text_input("姓名", key="patient_name")
        st.selectbox("性别", ["男", "女", "待确认"], key="sex")
        st.date_input("出生日期", key="birth_date")
        st.selectbox("数据使用同意状态", ["已同意", "未同意", "待确认"], key="consent_status")
        st.selectbox("患侧", ["左", "右", "双侧"], key="affected_side")
    with right:
        st.selectbox("病程状态", ["新诊断", "保守康复中", "复评", "已结束"], key="episode_status")
        st.selectbox("临床诊断把握度", ["确诊", "高度怀疑", "待鉴别"], key="diagnostic_confidence")
        st.number_input("症状持续时间（周）", min_value=0, max_value=520, step=1, key="symptom_duration_weeks")
        st.text_input("主运动/工作负荷", key="primary_activity")
        st.text_input("近期负荷变化", key="recent_load_change")
        st.text_input("主管医生", key="doctor")
        st.text_input("康复治疗师", key="therapist")
        st.checkbox("红旗或需要优先排除的情况（疑似断裂、伸膝无力、全身症状、明显积血/锁定等）", key="red_flag_present")
    if not st.session_state.patient_id and st.session_state.medical_record_no:
        if st.button("根据病历号生成患者 ID"):
            st.session_state.patient_id = patient_id_from_record(st.session_state.medical_record_no, st.session_state.patient_name)
            st.rerun()


def answer_key(question: str) -> str:
    return f"visa_{st.session_state.timepoint}_{question}"


def render_visa_p() -> int | None:
    st.subheader("VISA-P 中文版")
    st.caption(f"来源版本：{VISA_P_SOURCE_VERSION}。共 8 项、总分 0–100；分数越高表示症状更轻、功能更好。")
    st.selectbox("评估时间点", TIMEPOINTS, key="timepoint")
    st.date_input("评估日期", key="assessment_date")
    st.selectbox("填写来源", ["patient", "doctor-assisted", "therapist-assisted"], key="source_role")
    answers: dict[str, object] = {}
    for item in VISA_P_ITEMS:
        st.markdown(f"**{item.key[1:]}. {item.text}**")
        st.caption(f"{item.low_label} ← 请选择分数 → {item.high_label}")
        selected = st.radio(f"第{item.key[1:]}题评分", item_score_labels(item), horizontal=True, index=None, key=answer_key(item.key), label_visibility="collapsed")
        answers[item.key] = score_from_label(selected) if selected else None

    st.markdown("**7. 您目前是否正在进行运动或其他身体活动？**")
    activity_options = [training_option_label(label, score) for label, score in VISA_P_ACTIVITY_OPTIONS]
    selected_q7 = st.radio("活动参与", activity_options, index=None, key=answer_key("q7"), label_visibility="collapsed")
    answers["q7"] = next((score for label, score in VISA_P_ACTIVITY_OPTIONS if selected_q7 == training_option_label(label, score)), None)

    st.markdown("**8. 以下 A、B、C 三项中请选择其中一项填写：**")
    case = st.radio("情景", list(VISA_P_TRAINING_OPTIONS), format_func=lambda key: f"{key}. {VISA_P_TRAINING_OPTIONS[key][0]}", horizontal=True, index=None, key=answer_key("q8_case"), label_visibility="collapsed")
    answers["q8_case"] = case
    if case:
        duration_options = [training_option_label(label, score) for label, score in VISA_P_TRAINING_OPTIONS[case][1]]
        selected_duration = st.radio("训练/练习时间", duration_options, horizontal=True, index=None, key=answer_key("q8_duration"), label_visibility="collapsed")
        answers["q8_duration"] = next((score for label, score in VISA_P_TRAINING_OPTIONS[case][1] if selected_duration == training_option_label(label, score)), None)
    else:
        answers["q8_duration"] = None

    score = calculate_visa_p(answers)
    if score is None:
        st.info("请完成全部 8 项后生成总分；未完成状态不会计入趋势。")
    else:
        st.success(f"VISA-P 总分：{score}/100")
    st.session_state.current_visa_answers = answers
    st.session_state.current_visa_p_total = score
    return score


def clear_voice_review() -> None:
    """Discard transient transcript/review data after confirmation or cancellation."""
    for key in list(st.session_state):
        if key.startswith("voice_review_"):
            del st.session_state[key]


def prepare_voice_review(transcript: str) -> None:
    parsed = parse_rom_dictation(transcript)
    st.session_state.voice_review_transcript = parsed.transcript
    st.session_state.voice_review_warnings = list(parsed.uncertainties)
    st.session_state.voice_review_fields = list(parsed.values)
    for field, value in parsed.values.items():
        st.session_state[f"voice_review_{field}"] = value


def render_cloud_rom_voice_entry() -> None:
    st.markdown("#### 云端按住说话录入 ROM")
    st.caption("仅在康复师按住按钮时启动。浏览器将短句发送至其云端语音服务转写；本应用不接收或保存音频，只保留等待确认的文字。")
    voice_event = cloud_rom_voice_input(key="cloud_rom_voice")
    if st.session_state.pop("voice_apply_success", False):
        st.success("已写入 ROM 表单；请按常规流程保存。")
    if voice_event:
        event_id = str(voice_event.get("event_id", ""))
        if event_id and event_id != st.session_state.get("last_cloud_voice_event"):
            st.session_state.last_cloud_voice_event = event_id
            if voice_event.get("kind") == "final_transcript":
                prepare_voice_review(str(voice_event.get("transcript", "")))
            elif voice_event.get("kind") == "error":
                st.session_state.voice_review_error = str(voice_event.get("error", "语音服务不可用，请手工录入。"))

    if st.session_state.get("voice_review_error"):
        st.warning(st.session_state.voice_review_error)
        del st.session_state.voice_review_error

    fields = st.session_state.get("voice_review_fields", [])
    if not fields:
        return

    st.info("语音结果尚未写入。请逐项核对后再确认；确认前可直接修改。")
    st.caption(f"本次文字：{st.session_state.get('voice_review_transcript', '')}")
    for warning in st.session_state.get("voice_review_warnings", []):
        st.warning(warning)

    review_left, review_right = st.columns(2)
    with review_left:
        if "affected_side" in fields:
            st.selectbox("患侧（语音审核）", ["左", "右", "双侧"], key="voice_review_affected_side")
        if "rom_mode" in fields:
            st.selectbox("测量模式（语音审核）", ["主动", "被动"], key="voice_review_rom_mode")
        if "knee_flexion_deg" in fields:
            st.number_input("膝关节屈曲（度，语音审核）", min_value=0.0, max_value=160.0, step=1.0, key="voice_review_knee_flexion_deg")
    with review_right:
        if "knee_extension_deficit_deg" in fields:
            st.number_input("膝关节伸展受限（度，语音审核）", min_value=0.0, max_value=45.0, step=1.0, key="voice_review_knee_extension_deficit_deg")
        if "rom_method" in fields:
            st.selectbox("测量方法（语音审核）", ["量角器", "倾角仪", "目测", "其他"], key="voice_review_rom_method")
        if "rom_pain_or_limit" in fields:
            st.text_input("活动末端疼痛或限制（语音审核）", key="voice_review_rom_pain_or_limit")

    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button("确认并写入 ROM 表单", key="confirm_voice_rom", type="primary"):
            st.session_state.pending_voice_form_fields = {
                field: st.session_state[f"voice_review_{field}"] for field in fields
            }
            clear_voice_review()
            st.rerun()
    with cancel_col:
        if st.button("丢弃本次语音文字", key="cancel_voice_rom"):
            clear_voice_review()
            st.rerun()


def render_therapist_entry() -> None:
    st.subheader("康复师评估与周记录")
    render_cloud_rom_voice_entry()
    st.divider()
    left, right = st.columns(2)
    with left:
        st.caption("核心 ROM：伸展受限以正值记录；0°=完全伸直。")
        st.selectbox("测量模式", ["主动", "被动"], key="rom_mode")
        st.number_input("膝关节屈曲（度）", min_value=0.0, max_value=160.0, step=1.0, key="knee_flexion_deg")
        st.number_input("膝关节伸展受限（度）", min_value=0.0, max_value=45.0, step=1.0, key="knee_extension_deficit_deg")
        st.selectbox("测量方法", ["量角器", "倾角仪", "目测", "其他"], key="rom_method")
        st.text_input("活动末端疼痛或限制", key="rom_pain_or_limit")
    with right:
        st.number_input("康复周次", min_value=1, max_value=104, step=1, key="rehab_week_no")
        st.selectbox("康复阶段", REHAB_PHASES, key="rehab_phase")
        st.number_input("本周监督治疗次数", min_value=0, max_value=14, step=1, key="supervised_sessions")
        st.number_input("本周居家训练天数", min_value=0, max_value=7, step=1, key="home_training_days")
        st.number_input("依从性（%）", min_value=0.0, max_value=100.0, step=5.0, key="adherence_percent")
        st.number_input("训练负荷时疼痛 NRS", min_value=0.0, max_value=10.0, step=0.5, key="pain_during_load_nrs")
        st.number_input("训练后 24 小时疼痛 NRS", min_value=0.0, max_value=10.0, step=0.5, key="pain_24h_after_nrs")
        st.text_area("康复师解释", key="therapist_interpretation", height=100)


def build_records() -> tuple[dict[str, dict[str, object]], list[str]]:
    score = st.session_state.get("current_visa_p_total")
    status = visa_p_completion_status(st.session_state.get("current_visa_answers", {}))
    patient_id = st.session_state.patient_id or patient_id_from_record(st.session_state.medical_record_no, st.session_state.patient_name)
    identity = assessment_identity(patient_id, st.session_state.affected_side, st.session_state.timepoint, st.session_state.assessment_date)
    warnings = clinical_warnings(red_flag_present=bool(st.session_state.red_flag_present), diagnostic_confidence=str(st.session_state.diagnostic_confidence), visa_p_total=score, activity_pain_nrs=st.session_state.activity_pain_nrs)
    assessment = {
        "assessment_id": identity.assessment_id,
        "patient_id": patient_id,
        "episode_id": identity.episode_id,
        "timepoint": identity.timepoint,
        "assessment_date": identity.assessment_date,
        "affected_side": st.session_state.affected_side,
        "symptom_duration_weeks": st.session_state.symptom_duration_weeks,
        "activity_pain_nrs": st.session_state.activity_pain_nrs,
        "pain_activity_description": st.session_state.pain_activity_description,
        "visa_p_total": score,
        "visa_p_completion_status": status,
        "visa_p_respondent_source": st.session_state.source_role if status == "completed" else "not completed",
        "return_to_activity_status": st.session_state.return_to_activity_status,
        "imaging_summary": st.session_state.imaging_summary,
        "clinical_notes": st.session_state.clinical_notes,
        "warnings": "；".join(warnings),
    }
    baseline_visa = st.session_state.baseline_visa_p_total if identity.timepoint != "基线" else score
    baseline_pain = st.session_state.baseline_activity_pain_nrs if identity.timepoint != "基线" else st.session_state.activity_pain_nrs
    trend = trend_summary(baseline_visa, score, baseline_pain, st.session_state.activity_pain_nrs)
    rom = {
        "rom_id": stable_id("PT-ROM", identity.assessment_id, "膝关节", st.session_state.affected_side, st.session_state.rom_mode),
        "assessment_id": identity.assessment_id,
        "joint": "膝关节",
        "side": st.session_state.affected_side,
        "mode": st.session_state.rom_mode,
        "flexion_deg": st.session_state.knee_flexion_deg,
        "extension_deficit_deg": st.session_state.knee_extension_deficit_deg,
        "pain_or_limit": st.session_state.rom_pain_or_limit,
        "method": st.session_state.rom_method,
        "assessor": st.session_state.therapist or st.session_state.doctor,
        "measured_at": identity.assessment_date,
    }
    rehab = {
        "rehab_id": stable_id("PT-R", identity.episode_id, st.session_state.rehab_week_no),
        "episode_id": identity.episode_id,
        "week_no": st.session_state.rehab_week_no,
        "phase": st.session_state.rehab_phase,
        "supervised_sessions": st.session_state.supervised_sessions,
        "home_training_days": st.session_state.home_training_days,
        "adherence_percent": st.session_state.adherence_percent,
        "pain_during_load_nrs": st.session_state.pain_during_load_nrs,
        "pain_24h_after_nrs": st.session_state.pain_24h_after_nrs,
        "therapist_interpretation": st.session_state.therapist_interpretation,
    }
    outcome = {
        "outcome_id": stable_id("PT-O", identity.episode_id, identity.timepoint),
        "episode_id": identity.episode_id,
        "timepoint": identity.timepoint,
        "visa_p_total": score,
        "visa_p_change_from_baseline": trend.visa_p_delta,
        "activity_pain_nrs": st.session_state.activity_pain_nrs,
        "return_to_activity_status": st.session_state.return_to_activity_status,
        "escalation_or_surgery": st.session_state.escalation_or_surgery,
        "escalation_reason": st.session_state.escalation_reason,
    }
    report = {
        "report_id": stable_id("PT-REP", identity.assessment_id, MODEL_VERSION),
        "assessment_id": identity.assessment_id,
        "evidence_version": MODEL_VERSION,
        "model_status": "数据采集与趋势计算",
        "patient_report_text": patient_report(assessment, trend),
        "medical_record_text": medical_record_text(assessment, rom, trend),
    }
    records = {
        "patients": {"patient_id": patient_id, "medical_record_no": st.session_state.medical_record_no, "name": st.session_state.patient_name, "sex": st.session_state.sex, "birth_date": st.session_state.birth_date, "consent_status": st.session_state.consent_status},
        "episodes": {"episode_id": identity.episode_id, "patient_id": patient_id, "affected_side": st.session_state.affected_side, "status": st.session_state.episode_status, "symptom_duration_weeks": st.session_state.symptom_duration_weeks, "diagnostic_confidence": st.session_state.diagnostic_confidence, "red_flag_present": st.session_state.red_flag_present, "doctor": st.session_state.doctor, "therapist": st.session_state.therapist},
        "assessments": assessment,
        "rom": rom,
        "rehab": rehab,
        "outcomes": outcome,
        "reports": report,
    }
    return records, warnings


def render_report_and_save() -> None:
    st.subheader("趋势、患者解释与保存")
    left, right = st.columns(2)
    with left:
        st.number_input("基线 VISA-P 总分（随访时填写；基线评估无需填写）", min_value=0, max_value=100, step=1, key="baseline_visa_p_total")
        st.number_input("基线指定负荷疼痛 NRS（随访时填写）", min_value=0.0, max_value=10.0, step=0.5, key="baseline_activity_pain_nrs")
        st.number_input("本次指定负荷活动疼痛 NRS", min_value=0.0, max_value=10.0, step=0.5, key="activity_pain_nrs")
        st.text_input("疼痛对应的指定负荷活动", key="pain_activity_description")
        st.selectbox("重返活动状态", RETURN_TO_ACTIVITY, key="return_to_activity_status")
        st.selectbox("升级治疗/手术状态", ["无", "复评", "转诊", "已手术"], key="escalation_or_surgery")
        st.text_input("升级原因（如有）", key="escalation_reason")
    records, warnings = build_records()
    current = records["assessments"]
    trend = trend_summary(st.session_state.baseline_visa_p_total if st.session_state.timepoint != "基线" else current["visa_p_total"], current["visa_p_total"], st.session_state.baseline_activity_pain_nrs if st.session_state.timepoint != "基线" else current["activity_pain_nrs"], current["activity_pain_nrs"])
    with right:
        st.metric("当前 VISA-P", "未完成" if current["visa_p_total"] is None else f"{current['visa_p_total']}/100")
        st.metric("VISA-P 较基线", "无法计算" if trend.visa_p_delta is None else f"{trend.visa_p_delta:+d} 分")
        st.info(trend.interpretation)
        for warning in warnings:
            st.warning(warning)

    scenario = evidence_scenario_summary()
    with st.expander(scenario["title"], expanded=True):
        st.write(scenario["population"])
        st.write(f"- {scenario['structured_loading']}")
        st.write(f"- {scenario['eccentric_only']}")
        st.caption(f"{scenario['difference']}\n\n{scenario['source']}")

    report_id = str(records["reports"]["report_id"])
    if st.session_state.get("report_editor_source") != report_id:
        st.session_state.report_editor_source = report_id
        st.session_state.patient_report_editor = records["reports"]["patient_report_text"]
        st.session_state.medical_record_editor = records["reports"]["medical_record_text"]
    patient_text = st.text_area("患者解释（可编辑、复制）", key="patient_report_editor", height=260)
    record_text = st.text_area("病历文本（可编辑、复制）", key="medical_record_editor", height=180)
    records["reports"]["patient_report_text"] = patient_text
    records["reports"]["medical_record_text"] = record_text
    if st.button("根据当前结构化数据重置报告文本"):
        st.session_state.report_editor_source = ""
        st.rerun()
    st.divider()
    if st.button("保存到本地临床记录", type="primary"):
        if not st.session_state.medical_record_no or not st.session_state.patient_name:
            st.error("请先确认病历号和姓名，再保存。")
            return
        try:
            statuses = [f"{table}: {DEFAULT_STORAGE.upsert_record(table, record)[0]}" for table, record in records.items()]
            st.success("本地保存完成（" + "；".join(statuses) + "）。")
        except (ValueError, DuplicateRecordError) as exc:
            st.error(str(exc))

    config = configured_feishu()
    if not config:
        st.caption("飞书尚未配置：本地记录可用于原型验证。生产同步请在第二个授权闸门一次性配置 Secrets 和用户所有的 Base。")
        return
    if st.button("同步到用户所有的飞书多维表格"):
        try:
            client = FeishuBitableClient(config)
            token = client.resolve_bitable_token()
            table_ids = client.ensure_schema(token)
            for table, record in records.items():
                client.upsert_record(token, table_ids[table], table, record)
            st.success("已通过稳定临床 ID 更新飞书记录。")
        except (FeishuConfigurationError, FeishuAPIError, ValueError) as exc:
            st.error(f"本地记录未受影响；飞书同步失败：{exc}")


def render_sidebar() -> None:
    with st.sidebar:
        st.header("髌腱病临床计算器")
        st.caption("评估、康复分层与随访；不输出个人恢复概率或手术概率。")
        st.divider()
        st.write(f"模型版本：{MODEL_VERSION}")
        st.write("语音录入：云端网页按住说话（仅康复师 ROM 短句）；默认不保存音频，字段须确认后写入。")
        with st.expander("证据与限制"):
            st.markdown("- [髌腱病临床管理综述](https://pmc.ncbi.nlm.nih.gov/articles/PMC9528703/)")
            st.markdown("- [渐进肌腱负荷随机试验](https://pubmed.ncbi.nlm.nih.gov/33219115/)")
            st.markdown("- [预后队列研究（仅内部验证）](https://pmc.ncbi.nlm.nih.gov/articles/PMC12638584/)")


def main() -> None:
    init_state()
    require_clinical_access()
    render_sidebar()
    st.title("髌腱病评估、康复分层与随访")
    st.caption("先录入临床资料，再完成 VISA-P、康复评估、趋势解释与安全保存。")
    tabs = st.tabs(["① 首诊资料", "② VISA-P", "③ 康复评估", "④ 报告与保存"])
    with tabs[0]:
        render_patient_entry()
    with tabs[1]:
        render_visa_p()
    with tabs[2]:
        render_therapist_entry()
    with tabs[3]:
        render_report_and_save()


if __name__ == "__main__":
    main()
