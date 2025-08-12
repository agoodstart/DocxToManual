# --- STAGE 1: Packager ---
FROM public.ecr.aws/amazonlinux/amazonlinux:2023 AS packager

RUN yum install -y python3.13 python3.13-pip zip && yum clean all

# Force overwrite the symlinks
RUN ln -sf /usr/bin/python3.13 /usr/bin/python3 && \
    ln -sf /usr/bin/pip3.13 /usr/bin/pip3

WORKDIR /opt/build
COPY lambda_function.py .
COPY requirements.txt .
COPY package.sh .

RUN chmod +x package.sh

# --- STAGE 2: Local Tester ---
FROM public.ecr.aws/lambda/python:3.13 AS tester

# Set the default working directory Lambda expects
WORKDIR /var/task

# Copy function code
COPY lambda_function.py .
COPY requirements.txt .

# Install dependencies into /var/task
RUN pip install --no-cache-dir -r requirements.txt -t .

# Add Lambda Runtime Interface Emulator (RIE)
ADD https://github.com/aws/aws-lambda-runtime-interface-emulator/releases/latest/download/aws-lambda-rie /usr/local/bin/aws-lambda-rie
RUN chmod +x /usr/local/bin/aws-lambda-rie

# Default Lambda entrypoint
ENTRYPOINT ["/usr/local/bin/aws-lambda-rie", "/var/lang/bin/python3.13"]
CMD ["-m", "awslambdaric", "lambda_function.lambda_handler"]