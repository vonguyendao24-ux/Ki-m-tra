FROM python:3.10
WORKDIR /code
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
# Chạy file main.py
CMD ["python", "main.py"]
