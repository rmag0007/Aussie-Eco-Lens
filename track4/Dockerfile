FROM public.ecr.aws/lambda/python:3.12

# Install all dependencies including torch
RUN pip install azure-cosmos megadetector opencv-python-headless \
    Pillow tqdm pyyaml numpy torch torchvision --no-cache-dir

# Copy your code
COPY lambdas.py ml_inference.py ./

CMD ["lambdas.handler"]