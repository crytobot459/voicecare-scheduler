FROM python:3.11-slim
WORKDIR /app
COPY requirements-gradio.txt .
RUN pip install --no-cache-dir -r requirements-gradio.txt
COPY app.py .
COPY src/ ./src/
EXPOSE 7860
CMD ["python3", "app.py"]
