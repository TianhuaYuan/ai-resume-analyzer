from utils.privacy import sanitize_resume_module_for_ai


def test_project_name_is_not_treated_as_person_name():
    content = {
        "items": [
            {
                "name": "校招求职工作台",
                "role": "后端负责人",
                "description": "联系邮箱 owner@example.com，接口延迟降至 180ms",
            }
        ]
    }

    sanitized = sanitize_resume_module_for_ai("project_experience", content)

    assert sanitized["items"][0]["name"] == "校招求职工作台"
    assert sanitized["items"][0]["role"] == "后端负责人"
    assert "owner@example.com" not in sanitized["items"][0]["description"]


def test_basic_info_still_redacts_personal_fields():
    sanitized = sanitize_resume_module_for_ai(
        "basic_info",
        {"name": "陈晨", "phone": "13800001111", "email": "cc@example.com", "job_title": "后端开发"},
    )

    assert sanitized["name"] != "陈晨"
    assert sanitized["phone"] != "13800001111"
    assert sanitized["email"] != "cc@example.com"
    assert sanitized["job_title"] == "后端开发"
