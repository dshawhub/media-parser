from flask import Blueprint, render_template
from src.db import setting

bp = Blueprint('web', __name__)


@bp.route('/')
def index():
    """前台展示页面（Landing Page）"""
    return render_template(
        'landing.html',
        api_enabled=setting('global_api_enabled', '1') == '1',
    )
