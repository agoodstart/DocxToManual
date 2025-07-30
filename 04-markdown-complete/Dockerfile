# Use an official Python runtime as a parent image
FROM public.ecr.aws/amazonlinux/amazonlinux:2023

# Enable required repos and install Python 3.13 + dev tools
RUN yum install -y python3.13 python3.13-pip && yum clean all

# Optional: symlink for convenience
RUN ln -sf /usr/bin/python3.13 /usr/bin/python3 && \
    ln -sf /usr/bin/pip3.13 /usr/bin/pip3

WORKDIR /app

COPY requirements.txt .
RUN /usr/bin/pip3.13 install --no-cache-dir -r requirements.txt

COPY final_markdown.py .

CMD ["/usr/bin/python3.13", "final_markdown.py"]