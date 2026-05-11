from flask import Blueprint, render_template
web_bp = Blueprint('web', __name__)

@web_bp.route('/')
def index():
    return render_template('index.html')

@web_bp.route('/softpot')
def softpot():
    return render_template('softpot.html')

@web_bp.route('/flow')
def flow():
    return render_template('flow.html')
