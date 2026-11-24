from flask import Blueprint, render_template
from flask_login import login_required


territory_bp = Blueprint(
    "territory",
    __name__,
    url_prefix="/territory"
)


@territory_bp.route("/", methods=["GET"])
@login_required
def index():
    return render_template("territory/index.html")
