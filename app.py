from __future__ import annotations

from datetime import date
import hashlib
import hmac
from time import monotonic
import pandas as pd
import streamlit as st

from domain import REHAB_PHASES, RETURN_TO_ACTIVITY, TIMEPOINTS, clinical_warnings, patient_id_from_record
from feishu_adapter import RETIRED_TABLE_NAMES, FeishuAPIError, FeishuBitableClient, FeishuConfig, FeishuConfigurationError
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
from reporting import medical_record_text, medical_record_text_english, patient_report
from storage import DEFAULT_STORAGE, DuplicateRecordError


st.set_page_config(page_title="髌腱病临床计算器", page_icon="🦵", layout="wide")

APP_RELEASE = "PT-v0.5.2-responsive-sync-2026-07-18"

PRIMARY_LOAD_OPTIONS = ["跳跃/落地训练", "篮球", "排球", "羽毛球", "跑步", "足球", "网球/匹克球", "力量训练", "舞蹈/体操", "体力劳动", "久坐办公", "其他"]
PAIN_ACTIVITY_OPTIONS = ["跳跃落地", "单腿跳/连续跳", "跑步加速或冲刺", "爬楼/下楼", "深蹲", "弓步/蹲起", "久坐后起立", "训练后", "其他"]
HISTORY_CACHE_SECONDS = 20


def init_state() -> None:
    defaults: dict[str, object] = {
        "patient_id": "",
        "medical_record_no": "",
        "patient_name": "",
        "sex": "待确认",
        "birth_date": date(1990, 1, 1),
        "consent_status": "待确认",
        "height_cm": 170.0,
        "weight_kg": 65.0,
        "affected_side": "左",
        "episode_status": "新诊断",
        "diagnostic_confidence": "确诊",
        "red_flag_present": False,
        "symptom_duration_weeks": 12,
        "doctor": "",
        "therapist": "",
        "primary_activity": "跳跃/落地训练",
        "primary_activity_other": "",
        "recent_load_change": "未记录",
        "assessment_date": date.today(),
        "timepoint": "基线",
        "ultrasound_timepoint": "基线",
        "source_role": "doctor-assisted",
        "activity_pain_vas": 3.0,
        "pain_activity_description": "跳跃落地",
        "pain_activity_other": "",
        "target_sport": "",
        "target_activity_level": "休闲运动",
        "return_to_activity_status": "未恢复",
        "imaging_summary": "",
        "ultrasound_tendon_thickness_mm": 0.0,
        "ultrasound_date": date.today(),
        "ultrasound_note": "",
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


def patient_profile_by_id(patient_id: str) -> tuple[dict[str, object] | None, str]:
    """Retrieve one patient's basic profile for follow-up without re-entry."""
    config = configured_feishu()
    if config:
        try:
            client = FeishuBitableClient(config)
            token = client.resolve_bitable_token()
            table_id = client.ensure_schema(token)["patients"]
            for row in client.list_records(token, table_id):
                fields = dict(row.get("fields", {}))
                if str(fields.get("患者ID", "")) == patient_id:
                    return {
                        "medical_record_no": fields.get("病历号", ""),
                        "name": fields.get("姓名", ""),
                        "sex": fields.get("性别", "待确认"),
                        "birth_date": fields.get("出生日期"),
                        "height_cm": fields.get("身高（cm）", 170),
                        "weight_kg": fields.get("体重（kg）", 65),
                        "target_sport": fields.get("目标运动", ""),
                        "target_activity_level": fields.get("目标运动水平", "休闲运动"),
                        "consent_status": fields.get("同意状态", "待确认"),
                    }, "飞书患者主表"
        except (FeishuConfigurationError, FeishuAPIError, ValueError):
            pass
    for row in DEFAULT_STORAGE.list_records("patients"):
        if str(row.get("patient_id", "")) == patient_id:
            return row, "本地原型记录"
    return None, ""


def bmi_value() -> float | None:
    height_m = float(st.session_state.height_cm) / 100
    if height_m <= 0:
        return None
    return round(float(st.session_state.weight_kg) / (height_m * height_m), 1)


def selected_history_row(history: list[dict[str, object]], timepoint: str) -> dict[str, object] | None:
    candidates = [normalise_history_row(row) for row in history if str(normalise_history_row(row).get("timepoint")) == timepoint]
    if not candidates:
        return None
    return max(candidates, key=lambda row: _date_sort_value(row.get("assessment_date")))


def numeric_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_selected_timepoint() -> None:
    """Prefill the editable VAS fields from the selected patient's saved node."""
    patient_id = str(st.session_state.get("patient_id", "")).strip()
    if not patient_id:
        return
    history, _ = saved_assessment_history(patient_id)
    saved = selected_history_row(history, str(st.session_state.get("timepoint", "")))
    if not saved:
        return
    vas = numeric_or_none(saved.get("activity_pain_vas"))
    if vas is not None:
        st.session_state.activity_pain_vas = vas
    activity = str(saved.get("pain_activity_description", "")).strip()
    if activity in PAIN_ACTIVITY_OPTIONS:
        st.session_state.pain_activity_description = activity
        st.session_state.pain_activity_other = ""
    elif activity:
        st.session_state.pain_activity_description = "其他"
        st.session_state.pain_activity_other = activity


def load_selected_ultrasound_timepoint() -> None:
    """Load the saved ultrasound fields for the node selected in the ultrasound card."""
    patient_id = str(st.session_state.get("patient_id", "")).strip()
    if not patient_id:
        return
    history, _ = saved_assessment_history(patient_id)
    saved = selected_history_row(history, str(st.session_state.get("ultrasound_timepoint", "")))
    if not saved:
        st.session_state.ultrasound_tendon_thickness_mm = 0.0
        st.session_state.ultrasound_date = date.today()
        st.session_state.ultrasound_note = ""
        return
    thickness = numeric_or_none(saved.get("ultrasound_tendon_thickness_mm"))
    st.session_state.ultrasound_tendon_thickness_mm = thickness if thickness is not None else 0.0
    saved_date = _date_sort_value(saved.get("ultrasound_date"))
    st.session_state.ultrasound_date = saved_date.date() if not pd.isna(saved_date) else date.today()
    st.session_state.ultrasound_note = str(saved.get("ultrasound_note", ""))


def render_patient_history_strip(patient_id: str) -> None:
    if not patient_id:
        return
    history, _ = saved_assessment_history(patient_id)
    if not history:
        st.caption("尚无已保存评估；完成首诊后会在这里显示基线与随访记录。")
        return
    rows = []
    for point in TIMEPOINTS:
        row = selected_history_row(history, point)
        if row:
            visa = row.get("visa_p_total") if row.get("visa_p_total") not in (None, "") else "—"
            vas = row.get("activity_pain_vas") if row.get("activity_pain_vas") not in (None, "") else "—"
            thickness = numeric_or_none(row.get("ultrasound_tendon_thickness_mm"))
            ultrasound = "—" if thickness is None else f"{thickness:.1f} mm"
            rows.append({"节点": point, "状态": "已记录", "VISA-P": visa, "VAS": vas, "肌骨超声": ultrasound, "日期": row.get("assessment_date", "")})
        else:
            rows.append({"节点": point, "状态": "未记录", "VISA-P": "—", "VAS": "—", "肌骨超声": "—", "日期": ""})
    st.caption("患者历史概览（选择节点后，可更新该节点的评分、ROM 或肌骨超声）")
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


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
        if st.button("查询并带入已有患者资料", disabled=not bool(str(st.session_state.patient_id).strip())):
            profile, source = patient_profile_by_id(str(st.session_state.patient_id).strip())
            if not profile:
                st.warning("未找到该患者 ID。请核对后重试，或按首次患者完成基础资料录入。")
            else:
                st.session_state.medical_record_no = str(profile.get("medical_record_no", ""))
                st.session_state.patient_name = str(profile.get("name", ""))
                st.session_state.sex = str(profile.get("sex", "待确认"))
                if profile.get("birth_date"):
                    birth = profile["birth_date"]
                    st.session_state.birth_date = pd.to_datetime(birth, unit="ms" if isinstance(birth, (int, float)) else None).date()
                st.session_state.consent_status = str(profile.get("consent_status", "待确认"))
                st.session_state.height_cm = float(profile.get("height_cm") or 170)
                st.session_state.weight_kg = float(profile.get("weight_kg") or 65)
                st.session_state.target_sport = str(profile.get("target_sport", ""))
                st.session_state.target_activity_level = str(profile.get("target_activity_level", "休闲运动"))
                st.session_state.patient_profile_notice = f"已从{source}带入患者基础资料；本次随访无需重复录入。"
                st.rerun()
        if notice := st.session_state.pop("patient_profile_notice", ""):
            st.success(notice)
        st.text_input("病历号", key="medical_record_no")
        st.text_input("姓名", key="patient_name")
        st.selectbox("性别", ["男", "女", "待确认"], key="sex")
        st.date_input("出生日期", key="birth_date")
        st.selectbox("数据使用同意状态", ["已同意", "未同意", "待确认"], key="consent_status")
        st.selectbox("患侧", ["左", "右", "双侧"], key="affected_side")
        height, weight = st.columns(2)
        with height:
            st.number_input("身高（cm）", min_value=100.0, max_value=230.0, step=0.5, key="height_cm")
        with weight:
            st.number_input("体重（kg）", min_value=25.0, max_value=250.0, step=0.5, key="weight_kg")
        st.metric("BMI（自动计算）", "—" if bmi_value() is None else f"{bmi_value():.1f}")
        st.text_input("目标运动", key="target_sport", placeholder="例如：篮球、跑步、排球")
        st.selectbox("目标运动水平（自述）", ["日常活动", "休闲运动", "校队/业余竞赛", "半职业", "职业/精英"], key="target_activity_level")
        render_patient_history_strip(str(st.session_state.patient_id).strip())
    with right:
        st.selectbox("病程状态", ["新诊断", "保守康复中", "复评", "已结束"], key="episode_status")
        st.selectbox("临床诊断把握度", ["确诊", "高度怀疑", "待鉴别"], key="diagnostic_confidence")
        st.number_input("症状持续时间（周）", min_value=0, max_value=520, step=1, key="symptom_duration_weeks")
        st.selectbox("主运动/工作负荷", PRIMARY_LOAD_OPTIONS, key="primary_activity")
        if st.session_state.primary_activity == "其他":
            st.text_input("其他主运动/工作负荷", key="primary_activity_other")
        st.text_input("近期负荷变化", key="recent_load_change")
        st.text_input("主管医生", key="doctor")
        st.text_input("康复治疗师", key="therapist")
        st.checkbox("红旗或需要优先排除的情况（疑似断裂、伸膝无力、全身症状、明显积血/锁定等）", key="red_flag_present")
    if not st.session_state.patient_id and st.session_state.medical_record_no:
        if st.button("根据病历号生成患者 ID"):
            st.session_state.patient_id = patient_id_from_record(st.session_state.medical_record_no, st.session_state.patient_name)
            st.rerun()


def render_ultrasound_followup() -> None:
    st.subheader("肌骨超声随访")
    st.caption("可单独选择基线、6周、12周等节点。保存时只更新该患者该节点的超声字段，不会新增重复行或改动其他节点的评分。")
    patient_id = str(st.session_state.patient_id).strip()
    if not patient_id:
        st.info("请先填写或查询患者 ID，再保存肌骨超声。")
    st.selectbox("肌骨超声所属评估节点", TIMEPOINTS, key="ultrasound_timepoint", on_change=load_selected_ultrasound_timepoint)
    history, _ = saved_assessment_history(patient_id)
    saved = selected_history_row(history, str(st.session_state.ultrasound_timepoint)) if patient_id else None
    if saved and numeric_or_none(saved.get("ultrasound_tendon_thickness_mm")) is not None:
        saved_thickness = numeric_or_none(saved.get("ultrasound_tendon_thickness_mm"))
        st.info(f"已保存的{st.session_state.ultrasound_timepoint}肌骨超声：患侧髌腱厚度 {saved_thickness:.1f} mm。重新保存将更新该节点。")
    left, right = st.columns(2)
    with left:
        st.number_input("患侧髌腱厚度（mm）", min_value=0.0, max_value=20.0, step=0.1, key="ultrasound_tendon_thickness_mm", help="建议在同一测量位置复查；该指标用于治疗前后结构对比，不单独代表症状或功能。")
    with right:
        st.date_input("超声检查日期", key="ultrasound_date")
    st.text_input("超声备注（可选）", key="ultrasound_note", placeholder="如测量位置、低回声、血流或检查者描述")
    record = {
        "patient_id": patient_id,
        "timepoint": st.session_state.ultrasound_timepoint,
        "ultrasound_tendon_thickness_mm": st.session_state.ultrasound_tendon_thickness_mm or None,
        "ultrasound_date": st.session_state.ultrasound_date,
        "ultrasound_note": st.session_state.ultrasound_note,
    }
    if st.button("保存该节点肌骨超声并同步飞书", type="primary", key="save_ultrasound_section"):
        save_sections_to_feishu({"assessments": record}, ["assessments"], f"{st.session_state.ultrasound_timepoint} 的肌骨超声已保存。")


def answer_key(question: str) -> str:
    return f"visa_{st.session_state.timepoint}_{question}"


def render_visa_p() -> int | None:
    st.subheader("VISA-P 中文版")
    st.caption(f"来源版本：{VISA_P_SOURCE_VERSION}。共 8 项、总分 0–100；分数越高表示症状更轻、功能更好。")
    st.caption(f"当前评估节点：{st.session_state.timepoint}。切换节点请使用页面顶部的‘本次随访评估节点’。")
    st.date_input("评估日期", key="assessment_date")
    patient_id = str(st.session_state.patient_id).strip()
    history, _ = saved_assessment_history(patient_id)
    saved = selected_history_row(history, st.session_state.timepoint)
    if saved:
        saved_visa = saved.get("visa_p_total") if saved.get("visa_p_total") not in (None, "") else "—"
        saved_vas = saved.get("activity_pain_vas") if saved.get("activity_pain_vas") not in (None, "") else "—"
        st.info(f"已保存的{st.session_state.timepoint}结果：VISA-P {saved_visa}/100；VAS {saved_vas}/10。重新填写并保存将更新该节点。")
    st.slider("指定负荷活动疼痛 VAS（0=无痛，10=最痛）", min_value=0.0, max_value=10.0, value=float(st.session_state.activity_pain_vas), step=0.5, key="activity_pain_vas")
    st.selectbox("疼痛对应的指定负荷活动", PAIN_ACTIVITY_OPTIONS, key="pain_activity_description")
    if st.session_state.pain_activity_description == "其他":
        st.text_input("其他疼痛活动场景", key="pain_activity_other")
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


def clear_patient_history_cache() -> None:
    """Clear only this browser session's short-lived Feishu history snapshot."""

    st.session_state.pop("feishu_history_cache", None)


def saved_assessment_history(patient_id: str) -> tuple[list[dict[str, object]], str]:
    """Read follow-up history once per short UI interval, with local fallback.

    Streamlit reruns the complete script for every widget interaction and also
    renders every tab. Without this session cache, one slider drag can trigger
    repeated token, table-schema, and record-list calls to Feishu, leaving the
    interface in its grey loading state. Saves explicitly invalidate the cache.
    """
    config = configured_feishu()
    if config and patient_id:
        cache = st.session_state.get("feishu_history_cache")
        cache_key = (config.app_id, config.source, patient_id)
        if (
            isinstance(cache, dict)
            and cache.get("key") == cache_key
            and monotonic() - float(cache.get("loaded_at", 0)) < HISTORY_CACHE_SECONDS
        ):
            return list(cache.get("rows", [])), "飞书多维表格（已刷新）"
        try:
            client = FeishuBitableClient(config)
            token = client.resolve_bitable_token()
            table_id = client.existing_table_ids(token)["assessments"]
            rows = [dict(item.get("fields", {})) for item in client.list_records(token, table_id)]
            patient_rows = [row for row in rows if str(row.get("患者ID", "")) == patient_id]
            st.session_state.feishu_history_cache = {"key": cache_key, "loaded_at": monotonic(), "rows": patient_rows}
            return patient_rows, "飞书多维表格"
        except (FeishuConfigurationError, FeishuAPIError, ValueError):
            pass
    return [row for row in DEFAULT_STORAGE.list_records("assessments") if str(row.get("patient_id", "")) == patient_id], "本地原型记录"


def normalise_history_row(row: dict[str, object]) -> dict[str, object]:
    def first_present(*values: object) -> object:
        return next((value for value in values if value not in (None, "")), "")

    return {
        "patient_id": first_present(row.get("patient_id"), row.get("患者ID")),
        "timepoint": first_present(row.get("timepoint"), row.get("评估节点")),
        "assessment_date": first_present(row.get("assessment_date"), row.get("评估日期")),
        "visa_p_total": first_present(row.get("visa_p_total"), row.get("VISA-P总分")),
        "activity_pain_vas": first_present(row.get("activity_pain_vas"), row.get("指定负荷疼痛VAS"), row.get("activity_pain_nrs"), row.get("指定负荷疼痛NRS")),
        "ultrasound_tendon_thickness_mm": first_present(row.get("ultrasound_tendon_thickness_mm"), row.get("患侧髌腱厚度（mm）")),
        "ultrasound_date": first_present(row.get("ultrasound_date"), row.get("超声检查日期")),
        "ultrasound_note": first_present(row.get("ultrasound_note"), row.get("超声备注")),
        "return_to_activity_status": first_present(row.get("return_to_activity_status"), row.get("重返活动状态")),
    }


def with_current_assessment(history: list[dict[str, object]], current: dict[str, object]) -> list[dict[str, object]]:
    def natural_key(row: dict[str, object]) -> tuple[str, str]:
        return str(row["patient_id"]), str(row["timepoint"])

    current_key = natural_key(normalise_history_row(current))
    merged = [
        normalise_history_row(row)
        for row in history
        if natural_key(normalise_history_row(row)) != current_key
    ]
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


def save_sections_to_feishu(records: dict[str, object], tables: list[str], success_message: str) -> None:
    if not st.session_state.medical_record_no or not st.session_state.patient_name:
        st.error("请先确认病历号和姓名，再保存。")
        return
    config = configured_feishu()
    if not config:
        st.error("尚未配置飞书连接，无法保存。")
        return
    try:
        client = FeishuBitableClient(config)
        token = client.resolve_bitable_token()
        table_ids = client.ensure_schema(token)
        for table in tables:
            client.upsert_record(token, table_ids[table], table, dict(records[table]))
        clear_patient_history_cache()
        st.session_state.save_notice = success_message
        st.rerun()
    except (FeishuConfigurationError, FeishuAPIError, ValueError) as exc:
        st.error(f"飞书同步失败：{exc}")


def render_section_save(section: str) -> None:
    patient_id = st.session_state.patient_id or patient_id_from_record(st.session_state.medical_record_no, st.session_state.patient_name)
    history, _ = saved_assessment_history(patient_id)
    records, _, _ = build_records(history)
    if section == "initial":
        assessment = records["assessments"]
        records["assessments"] = {key: assessment[key] for key in ("patient_id", "timepoint", "assessment_date", "affected_side", "episode_status", "symptom_duration_weeks", "diagnostic_confidence", "red_flag_present", "doctor", "therapist", "primary_activity", "recent_load_change")}
        if st.button("保存本节点临床资料并同步飞书", type="primary", key="save_initial_section"):
            save_sections_to_feishu(records, ["patients", "assessments"], f"{st.session_state.timepoint} 的临床资料已保存；可继续填写评分、ROM 或肌骨超声。")
    elif section == "scores":
        assessment = records["assessments"]
        records["assessments"] = {key: assessment[key] for key in ("patient_id", "timepoint", "assessment_date", "activity_pain_vas", "pain_activity_description", "visa_p_total", "adherence_percent", "phase", "return_to_activity_status")}
        if st.button("保存本次临床评分并同步飞书", type="primary", key="save_score_section"):
            save_sections_to_feishu(records, ["assessments"], f"{st.session_state.timepoint} 的 VAS 与 VISA-P 已保存。")
    elif section == "rom":
        if st.button("保存本次 ROM 并同步飞书", type="primary", key="save_rom_section"):
            save_sections_to_feishu(records, ["rom"], f"{st.session_state.timepoint} 的 ROM 已保存。")


def build_records(history: list[dict[str, object]]) -> tuple[dict[str, object], list[str], object]:
    saved_current = selected_history_row(history, str(st.session_state.timepoint))
    entered_score = st.session_state.get("current_visa_p_total")
    score = entered_score if entered_score is not None else numeric_or_none((saved_current or {}).get("visa_p_total"))
    status = visa_p_completion_status(st.session_state.get("current_visa_answers", {}))
    patient_id = st.session_state.patient_id or patient_id_from_record(st.session_state.medical_record_no, st.session_state.patient_name)
    pain_vas = float(st.session_state.activity_pain_vas)
    primary_activity = st.session_state.primary_activity_other.strip() if st.session_state.primary_activity == "其他" else st.session_state.primary_activity
    pain_activity = st.session_state.pain_activity_other.strip() if st.session_state.pain_activity_description == "其他" else st.session_state.pain_activity_description
    warnings = clinical_warnings(red_flag_present=bool(st.session_state.red_flag_present), diagnostic_confidence=str(st.session_state.diagnostic_confidence), visa_p_total=score, activity_pain_nrs=pain_vas)
    assessment = {
        "patient_id": patient_id,
        "timepoint": st.session_state.timepoint,
        "assessment_date": st.session_state.assessment_date,
        "affected_side": st.session_state.affected_side,
        "symptom_duration_weeks": st.session_state.symptom_duration_weeks,
        "activity_pain_vas": pain_vas,
        "pain_activity_description": pain_activity,
        "visa_p_total": score,
        "return_to_activity_status": st.session_state.return_to_activity_status,
        "episode_status": st.session_state.episode_status,
        "diagnostic_confidence": st.session_state.diagnostic_confidence,
        "red_flag_present": st.session_state.red_flag_present,
        "primary_activity": primary_activity,
        "recent_load_change": st.session_state.recent_load_change,
        "doctor": st.session_state.doctor,
        "therapist": st.session_state.therapist,
        "week_no": st.session_state.rehab_week_no,
        "phase": st.session_state.rehab_phase,
        "adherence_percent": st.session_state.adherence_percent,
        "ultrasound_tendon_thickness_mm": numeric_or_none((saved_current or {}).get("ultrasound_tendon_thickness_mm")),
        "ultrasound_date": (saved_current or {}).get("ultrasound_date", ""),
        "ultrasound_note": (saved_current or {}).get("ultrasound_note", ""),
    }
    merged_history = with_current_assessment(history, assessment)
    baseline_visa, baseline_pain = baseline_for(merged_history, assessment)
    trend = trend_summary(baseline_visa, score, baseline_pain, pain_vas)
    assessor = st.session_state.therapist or st.session_state.doctor
    reference_side = reference_knee_side()
    # One wide ROM row per assessment. This keeps the clinical Base readable
    # while retaining all left/right knee, hip, and ankle values as columns.
    rom = {
        "patient_id": patient_id,
        "timepoint": st.session_state.timepoint,
        "affected_side": st.session_state.affected_side,
        "reference_knee_side": reference_side,
        "mode": "主动",
        "affected_knee_flexion_deg": st.session_state.affected_knee_flexion_deg,
        "affected_knee_extension_deficit_deg": st.session_state.affected_knee_extension_deficit_deg,
        "reference_knee_flexion_deg": st.session_state.reference_knee_flexion_deg,
        "reference_knee_extension_deficit_deg": st.session_state.reference_knee_extension_deficit_deg,
        "affected_hip_flexion_deg": st.session_state.affected_hip_flexion_deg,
        "affected_hip_extension_deg": st.session_state.affected_hip_extension_deg,
        "affected_hip_internal_rotation_deg": st.session_state.affected_hip_internal_rotation_deg,
        "affected_hip_external_rotation_deg": st.session_state.affected_hip_external_rotation_deg,
        "affected_ankle_knee_to_wall_cm": st.session_state.affected_ankle_knee_to_wall_cm,
        "method": st.session_state.rom_method,
        "assessor": assessor,
        "measured_at": st.session_state.assessment_date,
    }
    records: dict[str, object] = {
        "patients": {"patient_id": patient_id, "medical_record_no": st.session_state.medical_record_no, "name": st.session_state.patient_name, "sex": st.session_state.sex, "birth_date": st.session_state.birth_date, "height_cm": st.session_state.height_cm, "weight_kg": st.session_state.weight_kg, "bmi": bmi_value(), "target_sport": st.session_state.target_sport, "target_activity_level": st.session_state.target_activity_level, "consent_status": st.session_state.consent_status},
        "assessments": assessment,
        "rom": rom,
    }
    return records, warnings, trend


def render_followup_charts(history: list[dict[str, object]]) -> None:
    if not history:
        st.info("首次保存后，这里会自动出现 VISA-P 与 VAS 的随访曲线。")
        return
    all_records = pd.DataFrame(history)
    all_records["评估日期"] = all_records["assessment_date"].map(_date_sort_value)
    all_records["超声日期"] = all_records["ultrasound_date"].map(_date_sort_value)
    all_records["visa_p_total"] = pd.to_numeric(all_records["visa_p_total"], errors="coerce")
    all_records["activity_pain_vas"] = pd.to_numeric(all_records["activity_pain_vas"], errors="coerce")
    all_records["ultrasound_tendon_thickness_mm"] = pd.to_numeric(all_records["ultrasound_tendon_thickness_mm"], errors="coerce")
    frame = all_records.dropna(subset=["评估日期"]).sort_values("评估日期")
    st.markdown("#### 已保存随访趋势")
    visa_col, vas_col, ultrasound_col = st.columns(3)
    with visa_col:
        st.caption("VISA-P：越高表示功能越好")
        if frame.dropna(subset=["visa_p_total"]).empty:
            st.info("尚无已完成的 VISA-P。")
        else:
            st.line_chart(frame.set_index("评估日期")[["visa_p_total"]], height=230)
    with vas_col:
        st.caption("指定负荷疼痛 VAS：越低越好")
        if frame.dropna(subset=["activity_pain_vas"]).empty:
            st.info("尚无已保存的 VAS。")
        else:
            st.line_chart(frame.set_index("评估日期")[["activity_pain_vas"]], height=230)
    with ultrasound_col:
        st.caption("患侧髌腱厚度（mm）：结构随访对比")
        ultrasound_frame = all_records.dropna(subset=["超声日期", "ultrasound_tendon_thickness_mm"]).sort_values("超声日期")
        if ultrasound_frame.empty:
            st.info("尚无已保存的肌骨超声。")
        else:
            st.line_chart(ultrasound_frame.set_index("超声日期")[["ultrasound_tendon_thickness_mm"]], height=230)
    st.caption("超声厚度用于同一测量方案下的结构性治疗前后对比，应结合症状、功能和临床检查解释。")
    st.dataframe(all_records[["timepoint", "assessment_date", "visa_p_total", "activity_pain_vas", "ultrasound_tendon_thickness_mm", "ultrasound_date", "return_to_activity_status"]], hide_index=True, use_container_width=True)


def render_return_to_sport_bars(regular_percent: int, incomplete_percent: int) -> None:
    st.markdown("#### 重返原先运动水平")
    st.caption("以每 100 名相似患者为单位的 24 周沟通参考")
    for label, percent, color in (
        ("规律完成结构化康复", regular_percent, "#0f766e"),
        ("未规律完成结构化康复", incomplete_percent, "#9ca3af"),
    ):
        title, value = st.columns([4, 1])
        with title:
            st.markdown(f"**{label}**")
        with value:
            st.markdown(f"**{percent}%**")
        st.markdown(
            f'<div style="width:100%; background:#e5e7eb; border-radius:999px; height:22px; overflow:hidden; margin:-6px 0 18px;">'
            f'<div style="width:{percent}%; min-width:34px; height:22px; background:{color}; border-radius:999px;"></div></div>',
            unsafe_allow_html=True,
        )


def render_report_and_save() -> None:
    st.subheader("随访趋势、患者摘要与保存")
    if notice := st.session_state.pop("save_notice", ""):
        st.success(notice)
    left, right = st.columns(2)
    with left:
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
    config = configured_feishu()
    if config and config.bitable_url.startswith(("https://", "http://")):
        st.link_button("打开飞书随访数据库", config.bitable_url, use_container_width=False)
    render_followup_charts(visual_history)

    scenario = evidence_scenario_summary()
    reference = return_to_sport_reference(
        visa_p_total=current["visa_p_total"],
        activity_pain_vas=current["activity_pain_vas"],
        symptom_duration_weeks=current["symptom_duration_weeks"],
        adherence_percent=st.session_state.adherence_percent,
    )
    st.caption(f"目标：{st.session_state.target_sport or '尚未填写'} · {st.session_state.target_activity_level} · 24 周文献沟通参考")
    render_return_to_sport_bars(reference.regular_rehab_percent, reference.incomplete_rehab_percent)
    if reference.drivers:
        st.caption("本次参考已结合：" + "、".join(reference.drivers) + "。")
    with st.expander("查看研究依据", expanded=False):
        st.caption(str(scenario["difference"]))
        st.caption(str(scenario["source"]))

    report = {
        "patient_report_text": patient_report(current, trend),
        "medical_record_text": medical_record_text(current, dict(records["rom"]), trend),
        "medical_record_text_english": medical_record_text_english(current, dict(records["rom"]), trend),
    }
    with st.expander("供临床人员复制的简明文字", expanded=False):
        st.text_area("患者简明文字", value=str(report["patient_report_text"]), height=150, key="patient_report_preview")
        st.text_area("病历文本（中文）", value=str(report["medical_record_text"]), height=190, key="medical_record_preview")
        st.text_area("Clinical note (English)", value=str(report["medical_record_text_english"]), height=190, key="medical_record_english_preview")

    st.divider()
    st.caption("请使用首诊资料、临床评分或康复评估页内的保存按钮。报告会自动读取已保存的患者纵向记录。")


def render_sidebar() -> None:
    with st.sidebar:
        st.header("髌腱病临床计算器")
        st.caption("评估、ROM、康复进度与自动随访；不输出手术概率。")
        config = configured_feishu()
        if config and config.bitable_url.startswith(("https://", "http://")):
            st.link_button("打开飞书数据库", config.bitable_url, use_container_width=True)
        if config:
            with st.expander("管理员：清理旧表", expanded=True):
                st.caption("保留：患者主表、髌腱病评估表、ROM 综合评估。")
                st.caption("删除旧表：" + "、".join(RETIRED_TABLE_NAMES) + "；并只保留上述三张表的标准字段。此操作不可恢复。")
                if st.button("清理重复列与旧表", key="delete_retired_feishu_tables", type="secondary"):
                    try:
                        client = FeishuBitableClient(config)
                        token = client.resolve_bitable_token()
                        client.ensure_schema(token)
                        removed = client.delete_retired_tables(token)
                        removed_fields = client.delete_retired_id_fields(token)
                        pruned = client.prune_to_current_schema(token)
                        summary = removed + removed_fields + pruned
                        st.success("已清理：" + ("、".join(summary) if summary else "未发现需要清理的旧表或旧 ID 列") + "。")
                    except (FeishuConfigurationError, FeishuAPIError, ValueError) as exc:
                        st.error(f"旧表清理失败：{exc}")
        st.divider()
        st.write(f"工具版本：{APP_RELEASE}")
        st.caption(f"循证模型版本：{MODEL_VERSION}")
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
    st.selectbox("本次随访评估节点", TIMEPOINTS, key="timepoint", on_change=load_selected_timepoint, help="此选择同时用于临床资料、VISA-P、ROM 与报告；每位患者在每个节点只保留一条综合记录。")
    tabs = st.tabs(["① 首诊资料", "② VISA-P", "③ 康复评估", "④ 报告与保存"])
    with tabs[0]:
        render_patient_entry()
        st.divider()
        render_ultrasound_followup()
        st.divider()
        render_section_save("initial")
    with tabs[1]:
        render_visa_p()
        render_section_save("scores")
    with tabs[2]:
        render_therapist_entry()
        render_section_save("rom")
    with tabs[3]:
        render_report_and_save()


if __name__ == "__main__":
    main()
