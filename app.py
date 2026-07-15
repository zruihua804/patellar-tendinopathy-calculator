from __future__ import annotations

from datetime import date
import hashlib
import hmac
import pandas as pd
import streamlit as st

from domain import REHAB_PHASES, RETURN_TO_ACTIVITY, TIMEPOINTS, assessment_identity, clinical_warnings, patient_id_from_record, stable_id
from feishu import FeishuAPIError, FeishuBitableClient, FeishuConfig, FeishuConfigurationError
from model import MODEL_VERSION, evidence_scenario_summary, return_to_sport_reference, trend_summary
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
        "activity_pain_vas": 3.0,
        "pain_activity_description": "跳跃落地",
        "target_sport": "",
        "target_activity_level": "休闲运动",
        "return_to_activity_status": "未恢复",
        "imaging_summary": "",
        "clinical_notes": "",
        "affected_knee_flexion_deg": 135,
        "affected_knee_extension_deficit_deg": 0,
        "reference_knee_flexion_deg": 135,
        "reference_knee_extension_deficit_deg": 0,
        "reference_knee_side": "右",
        "affected_hip_flexion_deg": 120,
        "affected_hip_extension_deg": 20,
        "affected_hip_internal_rotation_deg": 35,
        "affected_hip_external_rotation_deg": 45,
        "affected_ankle_knee_to_wall_cm": 10,
        "rom_method": "量角器",
        "rehab_week_no": 1,
        "rehab_phase": "症状管理",
        "supervised_sessions": 0,
        "home_training_days": 0,
        "adherence_percent": 0.0,
        "pain_during_load_nrs": 0.0,
        "pain_24h_after_nrs": 0.0,
        "therapist_interpretation": "",
        "escalation_or_surgery": "无",
        "escalation_reason": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def secret_section(name: str) -> dict[str, object]:
    try:
        return dict(st.secrets.get(name, {}))
    except FileNotFoundError:
        return {}


def require_clinical_access() -> None:
    code = str(secret_section("app").get("clinical_access_code", "")).strip()
    if not code:
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
    st.caption("上传清晰的患者基本信息区域（姓名、病历号、性别、出生日期）。截图只在当前会话内本地解析，不会保存原图；结果必须确认后才会写入。")
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
    except Exception as exc:
        st.error(f"截图识别失败：{type(exc).__name__}。请上传清晰、完整的患者基本信息区域，或改为手动录入。")
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
    st.slider("指定负荷活动疼痛 VAS（0=无痛，10=最痛）", min_value=0.0, max_value=10.0, value=float(st.session_state.activity_pain_vas), step=0.5, key="activity_pain_vas")
    st.text_input("疼痛对应的指定负荷活动", key="pain_activity_description")
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


def render_therapist_entry() -> None:
    st.subheader("康复师评估与周记录")
    st.caption("拖动滑条记录 ROM；数值会作为本次评估的结构化字段保存。伸展受限以正值记录，0°=完全伸直。")
    left, right = st.columns(2)
    with left:
        st.markdown("#### 膝关节：患侧 vs 健侧")
        st.slider("患侧膝屈曲（度）", 0, 160, key="affected_knee_flexion_deg")
        st.slider("患侧膝伸展受限（度）", 0, 45, key="affected_knee_extension_deficit_deg")
        if st.session_state.affected_side in {"左", "右"}:
            st.caption(f"健侧自动标记为：{'右' if st.session_state.affected_side == '左' else '左'}侧")
        else:
            st.selectbox("双侧症状时的对照侧", ["左", "右"], key="reference_knee_side")
        st.slider("健侧/对照侧膝屈曲（度）", 0, 160, key="reference_knee_flexion_deg")
        st.slider("健侧/对照侧膝伸展受限（度）", 0, 45, key="reference_knee_extension_deficit_deg")
        st.markdown("#### 患侧髋关节")
        st.slider("髋屈曲（度）", 0, 150, key="affected_hip_flexion_deg")
        st.slider("髋伸展（度）", 0, 45, key="affected_hip_extension_deg")
        st.slider("髋内旋（度）", 0, 60, key="affected_hip_internal_rotation_deg")
        st.slider("髋外旋（度）", 0, 80, key="affected_hip_external_rotation_deg")
    with right:
        st.markdown("#### 患侧踝关节")
        st.slider("踝背屈：膝靠墙测试距离（cm）", 0, 20, key="affected_ankle_knee_to_wall_cm", help="膝靠墙测试通常记录足趾到墙的距离（cm），不是角度。")
        st.selectbox("测量方法", ["量角器", "倾角仪", "目测", "其他"], key="rom_method")
        st.divider()
        st.markdown("#### 本周康复记录")
        st.number_input("康复周次", min_value=1, max_value=104, step=1, key="rehab_week_no")
        st.selectbox("康复阶段", REHAB_PHASES, key="rehab_phase")
        st.number_input("本周监督治疗次数", min_value=0, max_value=14, step=1, key="supervised_sessions")
        st.number_input("本周居家训练天数", min_value=0, max_value=7, step=1, key="home_training_days")
        st.number_input("依从性（%）", min_value=0.0, max_value=100.0, step=5.0, key="adherence_percent")
        st.number_input("训练负荷时疼痛 NRS", min_value=0.0, max_value=10.0, step=0.5, key="pain_during_load_nrs")
        st.number_input("训练后 24 小时疼痛 NRS", min_value=0.0, max_value=10.0, step=0.5, key="pain_24h_after_nrs")
        st.text_area("康复师解释", key="therapist_interpretation", height=100)


def reference_knee_side() -> str:
    if st.session_state.affected_side == "左":
        return "右"
    if st.session_state.affected_side == "右":
        return "左"
    return str(st.session_state.reference_knee_side)


def _date_sort_value(value: object) -> pd.Timestamp:
    if isinstance(value, (int, float)):
        return pd.to_datetime(value, unit="ms", errors="coerce")
    return pd.to_datetime(value, errors="coerce")


def saved_assessment_history(patient_id: str) -> tuple[list[dict[str, object]], str]:
    """Use the user-owned Base for follow-up history, with local fallback in prototype mode."""
    config = configured_feishu()
    if config and patient_id:
        try:
            client = FeishuBitableClient(config)
            token = client.resolve_bitable_token()
            table_id = client.ensure_schema(token)["assessments"]
            rows = [dict(item.get("fields", {})) for item in client.list_records(token, table_id)]
            return [row for row in rows if str(row.get("患者ID", "")) == patient_id], "飞书多维表格"
        except (FeishuConfigurationError, FeishuAPIError, ValueError):
            pass
    return [row for row in DEFAULT_STORAGE.list_records("assessments") if str(row.get("patient_id", "")) == patient_id], "本地原型记录"


def normalise_history_row(row: dict[str, object]) -> dict[str, object]:
    def first_present(*values: object) -> object:
        return next((value for value in values if value not in (None, "")), "")

    return {
        "assessment_id": first_present(row.get("assessment_id"), row.get("评估ID")),
        "timepoint": first_present(row.get("timepoint"), row.get("评估节点")),
        "assessment_date": first_present(row.get("assessment_date"), row.get("评估日期")),
        "visa_p_total": first_present(row.get("visa_p_total"), row.get("VISA-P总分")),
        "activity_pain_vas": first_present(row.get("activity_pain_vas"), row.get("指定负荷疼痛VAS"), row.get("activity_pain_nrs"), row.get("指定负荷疼痛NRS")),
        "return_to_activity_status": first_present(row.get("return_to_activity_status"), row.get("重返活动状态")),
    }


def with_current_assessment(history: list[dict[str, object]], current: dict[str, object]) -> list[dict[str, object]]:
    current_id = str(current["assessment_id"])
    merged = [normalise_history_row(row) for row in history if str(normalise_history_row(row)["assessment_id"]) != current_id]
    merged.append(normalise_history_row(current))
    return sorted(merged, key=lambda row: _date_sort_value(row["assessment_date"]))


def baseline_for(history: list[dict[str, object]], current: dict[str, object]) -> tuple[object | None, object | None]:
    if current["timepoint"] == "基线":
        return current["visa_p_total"], current["activity_pain_vas"]
    baseline = next((row for row in history if row.get("timepoint") == "基线"), None)
    if not baseline:
        return None, None
    return baseline.get("visa_p_total"), baseline.get("activity_pain_vas")


def table_records(records: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    flattened: list[tuple[str, dict[str, object]]] = []
    for table, value in records.items():
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            flattened.append((table, dict(row)))
    return flattened


def build_records(history: list[dict[str, object]]) -> tuple[dict[str, object], list[str], object]:
    score = st.session_state.get("current_visa_p_total")
    status = visa_p_completion_status(st.session_state.get("current_visa_answers", {}))
    patient_id = st.session_state.patient_id or patient_id_from_record(st.session_state.medical_record_no, st.session_state.patient_name)
    identity = assessment_identity(patient_id, st.session_state.affected_side, st.session_state.timepoint, st.session_state.assessment_date)
    pain_vas = float(st.session_state.activity_pain_vas)
    warnings = clinical_warnings(red_flag_present=bool(st.session_state.red_flag_present), diagnostic_confidence=str(st.session_state.diagnostic_confidence), visa_p_total=score, activity_pain_nrs=pain_vas)
    assessment = {
        "assessment_id": identity.assessment_id,
        "patient_id": patient_id,
        "episode_id": identity.episode_id,
        "timepoint": identity.timepoint,
        "assessment_date": identity.assessment_date,
        "affected_side": st.session_state.affected_side,
        "symptom_duration_weeks": st.session_state.symptom_duration_weeks,
        "activity_pain_nrs": pain_vas,
        "activity_pain_vas": pain_vas,
        "pain_activity_description": st.session_state.pain_activity_description,
        "visa_p_total": score,
        "visa_p_completion_status": status,
        "visa_p_respondent_source": st.session_state.source_role if status == "completed" else "not completed",
        "target_sport": st.session_state.target_sport,
        "target_activity_level": st.session_state.target_activity_level,
        "return_to_activity_status": st.session_state.return_to_activity_status,
        "imaging_summary": st.session_state.imaging_summary,
        "clinical_notes": st.session_state.clinical_notes,
        "warnings": "；".join(warnings),
    }
    merged_history = with_current_assessment(history, assessment)
    baseline_visa, baseline_pain = baseline_for(merged_history, assessment)
    trend = trend_summary(baseline_visa, score, baseline_pain, pain_vas)
    assessor = st.session_state.therapist or st.session_state.doctor
    reference_side = reference_knee_side()
    rom_rows = [
        {"rom_id": stable_id("PT-ROM", identity.assessment_id, "knee", "affected"), "assessment_id": identity.assessment_id, "joint": "膝关节", "side": st.session_state.affected_side, "comparison_role": "患侧", "mode": "主动", "flexion_deg": st.session_state.affected_knee_flexion_deg, "extension_deficit_deg": st.session_state.affected_knee_extension_deficit_deg, "method": st.session_state.rom_method, "assessor": assessor, "measured_at": identity.assessment_date},
        {"rom_id": stable_id("PT-ROM", identity.assessment_id, "knee", "reference"), "assessment_id": identity.assessment_id, "joint": "膝关节", "side": reference_side, "comparison_role": "健侧/对照侧", "mode": "主动", "flexion_deg": st.session_state.reference_knee_flexion_deg, "extension_deficit_deg": st.session_state.reference_knee_extension_deficit_deg, "method": st.session_state.rom_method, "assessor": assessor, "measured_at": identity.assessment_date},
        {"rom_id": stable_id("PT-ROM", identity.assessment_id, "hip", "affected"), "assessment_id": identity.assessment_id, "joint": "髋关节", "side": st.session_state.affected_side, "comparison_role": "患侧同侧", "mode": "主动", "flexion_deg": st.session_state.affected_hip_flexion_deg, "extension_deg": st.session_state.affected_hip_extension_deg, "internal_rotation_deg": st.session_state.affected_hip_internal_rotation_deg, "external_rotation_deg": st.session_state.affected_hip_external_rotation_deg, "method": st.session_state.rom_method, "assessor": assessor, "measured_at": identity.assessment_date},
        {"rom_id": stable_id("PT-ROM", identity.assessment_id, "ankle", "affected"), "assessment_id": identity.assessment_id, "joint": "踝关节", "side": st.session_state.affected_side, "comparison_role": "患侧同侧", "mode": "主动", "knee_to_wall_cm": st.session_state.affected_ankle_knee_to_wall_cm, "method": st.session_state.rom_method, "assessor": assessor, "measured_at": identity.assessment_date},
    ]
    rehab = {"rehab_id": stable_id("PT-R", identity.episode_id, st.session_state.rehab_week_no), "episode_id": identity.episode_id, "week_no": st.session_state.rehab_week_no, "phase": st.session_state.rehab_phase, "supervised_sessions": st.session_state.supervised_sessions, "home_training_days": st.session_state.home_training_days, "adherence_percent": st.session_state.adherence_percent, "pain_during_load_nrs": st.session_state.pain_during_load_nrs, "pain_24h_after_nrs": st.session_state.pain_24h_after_nrs, "therapist_interpretation": st.session_state.therapist_interpretation}
    outcome = {"outcome_id": stable_id("PT-O", identity.episode_id, identity.timepoint), "episode_id": identity.episode_id, "timepoint": identity.timepoint, "visa_p_total": score, "visa_p_change_from_baseline": trend.visa_p_delta, "activity_pain_nrs": pain_vas, "activity_pain_vas": pain_vas, "return_to_activity_status": st.session_state.return_to_activity_status, "escalation_or_surgery": st.session_state.escalation_or_surgery, "escalation_reason": st.session_state.escalation_reason}
    report = {"report_id": stable_id("PT-REP", identity.assessment_id, MODEL_VERSION), "assessment_id": identity.assessment_id, "evidence_version": MODEL_VERSION, "model_status": "数据采集与趋势计算", "patient_report_text": patient_report(assessment, trend), "medical_record_text": medical_record_text(assessment, rom_rows, trend)}
    records: dict[str, object] = {
        "patients": {"patient_id": patient_id, "medical_record_no": st.session_state.medical_record_no, "name": st.session_state.patient_name, "sex": st.session_state.sex, "birth_date": st.session_state.birth_date, "consent_status": st.session_state.consent_status},
        "episodes": {"episode_id": identity.episode_id, "patient_id": patient_id, "affected_side": st.session_state.affected_side, "status": st.session_state.episode_status, "symptom_duration_weeks": st.session_state.symptom_duration_weeks, "diagnostic_confidence": st.session_state.diagnostic_confidence, "red_flag_present": st.session_state.red_flag_present, "doctor": st.session_state.doctor, "therapist": st.session_state.therapist},
        "assessments": assessment,
        "rom": rom_rows,
        "rehab": rehab,
        "outcomes": outcome,
        "reports": report,
    }
    return records, warnings, trend


def render_followup_charts(history: list[dict[str, object]]) -> None:
    if not history:
        st.info("首次保存后，这里会自动出现 VISA-P 与 VAS 的随访曲线。")
        return
    frame = pd.DataFrame(history)
    frame["评估日期"] = frame["assessment_date"].map(_date_sort_value)
    frame["visa_p_total"] = pd.to_numeric(frame["visa_p_total"], errors="coerce")
    frame["activity_pain_vas"] = pd.to_numeric(frame["activity_pain_vas"], errors="coerce")
    frame = frame.dropna(subset=["评估日期"]).sort_values("评估日期")
    st.markdown("#### 已保存随访趋势")
    visa_col, vas_col = st.columns(2)
    with visa_col:
        st.caption("VISA-P：越高表示功能越好")
        st.line_chart(frame.set_index("评估日期")[["visa_p_total"]], height=230)
    with vas_col:
        st.caption("指定负荷疼痛 VAS：越低越好")
        st.line_chart(frame.set_index("评估日期")[["activity_pain_vas"]], height=230)
    st.dataframe(frame[["timepoint", "assessment_date", "visa_p_total", "activity_pain_vas", "return_to_activity_status"]], hide_index=True, use_container_width=True)


def render_report_and_save() -> None:
    st.subheader("随访趋势、患者摘要与保存")
    if notice := st.session_state.pop("save_notice", ""):
        st.success(notice)
    left, right = st.columns(2)
    with left:
        st.text_input("希望重返的运动", key="target_sport", placeholder="例如：篮球、跑步、排球")
        st.selectbox("目标运动水平（自述）", ["日常活动", "休闲运动", "校队/业余竞赛", "半职业", "职业/精英"], key="target_activity_level")
        st.selectbox("重返活动状态", RETURN_TO_ACTIVITY, key="return_to_activity_status")
    with right:
        st.selectbox("升级治疗/手术状态", ["无", "复评", "转诊", "已手术"], key="escalation_or_surgery")
        st.text_input("升级原因（如有）", key="escalation_reason")
        st.caption("基线与每次随访均从已保存记录自动读取；不再手工填写基线分数。")

    patient_id = st.session_state.patient_id or patient_id_from_record(st.session_state.medical_record_no, st.session_state.patient_name)
    history, history_source = saved_assessment_history(patient_id)
    records, warnings, trend = build_records(history)
    current = dict(records["assessments"])
    visual_history = with_current_assessment(history, current)
    metric_left, metric_mid, metric_right = st.columns(3)
    with metric_left:
        st.metric("当前 VISA-P", "未完成" if current["visa_p_total"] is None else f"{current['visa_p_total']}/100")
    with metric_mid:
        st.metric("当前指定负荷疼痛 VAS", f"{current['activity_pain_vas']}/10")
    with metric_right:
        st.metric("VISA-P 较基线", "等待基线与本次量表完成" if trend.visa_p_delta is None else f"{trend.visa_p_delta:+d} 分")
    st.info(trend.interpretation)
    for warning in warnings:
        st.warning(warning)
    st.caption(f"趋势来源：{history_source}；当前未保存的评估以预览形式显示。")
    render_followup_charts(visual_history)

    scenario = evidence_scenario_summary()
    reference = return_to_sport_reference(
        visa_p_total=current["visa_p_total"],
        activity_pain_vas=current["activity_pain_vas"],
        symptom_duration_weeks=current["symptom_duration_weeks"],
        adherence_percent=st.session_state.adherence_percent,
    )
    st.markdown("#### 重返原先运动水平")
    st.caption(f"目标：{st.session_state.target_sport or '尚未填写'} · {st.session_state.target_activity_level} · 24 周文献沟通参考")
    reference_frame = pd.DataFrame(
        {
            "康复路径": ["规律完成结构化康复", "未规律完成结构化康复"],
            "重返原先运动水平参考（%）": [reference.regular_rehab_percent, reference.incomplete_rehab_percent],
        }
    ).set_index("康复路径")
    st.bar_chart(reference_frame, height=250)
    if reference.drivers:
        st.caption("本次参考已结合：" + "、".join(reference.drivers) + "。")
    with st.expander("查看研究依据", expanded=False):
        st.caption(str(scenario["difference"]))
        st.caption(str(scenario["source"]))

    report = dict(records["reports"])
    with st.expander("供临床人员复制的简明文字", expanded=False):
        patient_text = st.text_area("患者简明文字", value=str(report["patient_report_text"]), height=150, key=f"patient_report_{report['report_id']}")
        record_text = st.text_area("病历文本", value=str(report["medical_record_text"]), height=210, key=f"medical_record_{report['report_id']}")
        report["patient_report_text"] = patient_text
        report["medical_record_text"] = record_text
        records["reports"] = report

    st.divider()
    if st.button("保存到本地临床记录", type="primary"):
        if not st.session_state.medical_record_no or not st.session_state.patient_name:
            st.error("请先确认病历号和姓名，再保存。")
            return
        try:
            statuses = [f"{table}: {DEFAULT_STORAGE.upsert_record(table, record)[0]}" for table, record in table_records(records)]
            st.session_state.save_notice = "本地保存完成（" + "；".join(statuses) + "）。随访图已自动刷新。"
            st.rerun()
        except (ValueError, DuplicateRecordError) as exc:
            st.error(str(exc))

    config = configured_feishu()
    if not config:
        return
    if st.button("保存并同步到飞书多维表格"):
        try:
            client = FeishuBitableClient(config)
            token = client.resolve_bitable_token()
            table_ids = client.ensure_schema(token)
            for table, record in table_records(records):
                client.upsert_record(token, table_ids[table], table, record)
            st.session_state.save_notice = "已保存并同步飞书；随访图已自动从飞书记录刷新。"
            st.rerun()
        except (FeishuConfigurationError, FeishuAPIError, ValueError) as exc:
            st.error(f"本地记录未受影响；飞书同步失败：{exc}")


def render_sidebar() -> None:
    with st.sidebar:
        st.header("髌腱病临床计算器")
        st.caption("评估、ROM、康复进度与自动随访；不输出手术概率。")
        st.divider()
        st.write(f"模型版本：{MODEL_VERSION}")
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
