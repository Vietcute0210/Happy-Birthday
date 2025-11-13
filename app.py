import io
import csv
import os
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
import qrcode
# from datetime import datetime # Đã import ở trên

app = Flask(__name__)
app.config['SECRET_KEY'] = 'replace-this-with-a-secret'
# SQLite DB file
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/wishes.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --------------------
# Models
# --------------------
class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False) 
    slug = db.Column(db.String(120), unique=True, nullable=False) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Cột 'date' đã được xóa trong model này (Đúng theo file bạn gửi)
    wishes = db.relationship('Wish', backref='event', cascade="all, delete-orphan")

class Wish(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    sender_name = db.Column(db.String(120))
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# --------------------
# Helpers
# --------------------
def ensure_db():
    # tạo DB nếu chưa tồn tại
    db.create_all()

def generate_qr_bytes(url, box_size=10):
    qr = qrcode.QRCode(box_size=box_size, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


# --------------------
# Public Routes (Wish submission, Index, QR)
# --------------------
@app.route('/')
def index():
    # trang list event + form tạo event nhanh (nhập tên sự kiện + slug)
    events = Event.query.order_by(Event.created_at.desc()).all()
    return render_template('index.html', events=events)


@app.route('/create_event', methods=['POST'])
def create_event():
    name = request.form.get('name', '').strip()
    slug = request.form.get('slug', '').strip()
    if not name or not slug:
        flash('Bạn cần nhập tên và slug (ví dụ: john-25).', 'danger')
        return redirect(url_for('index'))
    if Event.query.filter_by(slug=slug).first():
        flash('Slug đã tồn tại. Hãy chọn slug khác.', 'danger')
        return redirect(url_for('index'))
    ev = Event(name=name, slug=slug)
    db.session.add(ev)
    db.session.commit()
    flash('Tạo sự kiện thành công.', 'success')
    return redirect(url_for('index'))

@app.route('/delete_event/<int:event_id>', methods=['POST'])
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    flash('Sự kiện đã được xóa thành công!', 'success')
    return redirect(url_for('index')) 

@app.route('/wish/<slug>', methods=['GET'])
def wish_form(slug):
    ev = Event.query.filter_by(slug=slug).first_or_404()
    return render_template('wish.html', event=ev)


@app.route('/wish/<slug>/submit', methods=['POST'])
def submit_wish(slug):
    ev = Event.query.filter_by(slug=slug).first_or_404()
    sender_name = request.form.get('sender_name', '').strip()
    message = request.form.get('message', '').strip()
    if not message:
        flash('Lời chúc không được để trống', 'danger')
        return redirect(url_for('wish_form', slug=slug))
    w = Wish(event=ev, sender_name=sender_name or 'Ẩn danh', message=message)
    db.session.add(w)
    db.session.commit()
    flash('Cảm ơn! Lời chúc đã được lưu.', 'success')
    return redirect(url_for('wish_form', slug=slug))


@app.route('/qr/<slug>.png')
def qr_image(slug):
    ev = Event.query.filter_by(slug=slug).first_or_404()
    target_url = url_for('wish_form', slug=ev.slug, _external=True)
    buf = generate_qr_bytes(target_url)
    return send_file(buf, mimetype='image/png', as_attachment=False, download_name=f'{slug}.png')

# --------------------
# Display Route (New Feature)
# --------------------
@app.route('/display/<slug>')
def display_view(slug):
    ev = Event.query.filter_by(slug=slug).first_or_404()
    # Yêu cầu file template display.html
    return render_template('display.html', event=ev)


# --------------------
# Admin Routes
# --------------------
@app.route('/admin/<slug>')
def admin_view(slug):
    ev = Event.query.filter_by(slug=slug).first_or_404()
    wishes = Wish.query.filter_by(event_id=ev.id).order_by(Wish.created_at.desc()).all()
    return render_template('admin.html', event=ev, wishes=wishes)


@app.route('/admin/<slug>/export')
def admin_export(slug):
    ev = Event.query.filter_by(slug=slug).first_or_404()
    wishes = Wish.query.filter_by(event_id=ev.id).order_by(Wish.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'sender_name', 'message', 'created_at'])
    for w in wishes:
        writer.writerow([w.id, w.sender_name, w.message, w.created_at.isoformat()])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8')),
                     mimetype='text/csv',
                     as_attachment=True,
                     download_name=f'wishes_{ev.slug}.csv')


@app.route('/admin/<slug>/delete/<int:wish_id>', methods=['POST'])
def admin_delete_wish(slug, wish_id):
    ev = Event.query.filter_by(slug=slug).first_or_404()
    w = Wish.query.filter_by(id=wish_id, event_id=ev.id).first_or_404()
    db.session.delete(w)
    db.session.commit()
    flash('Đã xóa lời chúc.', 'success')
    return redirect(url_for('admin_view', slug=slug))


# --------------------
# API Routes
# --------------------
@app.route('/api/<slug>/summary')
def api_summary(slug):
    ev = Event.query.filter_by(slug=slug).first_or_404()
    total = Wish.query.filter_by(event_id=ev.id).count()
    last5 = Wish.query.filter_by(event_id=ev.id).order_by(Wish.created_at.desc()).limit(5).all()
    return jsonify({
        'event': ev.name,
        'slug': ev.slug,
        'total': total,
        'last5': [{'sender': w.sender_name, 'message': w.message, 'when': w.created_at.isoformat()} for w in last5]
    })

@app.route('/api/<slug>/wishes')
def api_wishes(slug):
    ev = Event.query.filter_by(slug=slug).first_or_404()
    
    # Lấy TẤT CẢ lời chúc, sắp xếp theo thời gian gửi (cũ nhất lên trước)
    wishes = Wish.query.filter_by(event_id=ev.id).order_by(Wish.created_at.asc()).all()
    
    # Trả về JSON
    return jsonify({
        'event_name': ev.name,
        'slug': ev.slug,
        'total': len(wishes),
        'wishes': [{
            'id': w.id,
            'sender': w.sender_name,
            'message': w.message,
            'when': w.created_at.strftime("%H:%M") 
        } for w in wishes]
    })


# --------------------
# Run
# --------------------
if __name__ == '__main__':
    with app.app_context():
        ensure_db() # Gọi hàm tạo bảng
    app.run(host='0.0.0.0', port=5000, debug=True)