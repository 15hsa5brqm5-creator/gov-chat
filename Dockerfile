# استخدام إصدار Python 3.10 الذي يعمل مع جميع مكتباتنا
FROM python:3.10-slim

# تعيين دليل العمل داخل الحاوية
WORKDIR /app

# نسخ ملف المتطلبات أولاً (للاستفادة من التخزين المؤقت)
COPY requirements.txt .

# تثبيت المتطلبات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع
COPY . .

# إخبار Render بالمنفذ الذي سيستخدمه التطبيق
EXPOSE 10000

# متغير البيئة للمنفذ
ENV PORT=10000

# أمر تشغيل الخادم
CMD ["gunicorn", "-k", "gevent", "-w", "1", "app:app"]
