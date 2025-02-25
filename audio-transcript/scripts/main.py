import json
import logging
import os
import time
from sys import stdout

import pika
from pika.exchange_type import ExchangeType

from service import TranscriptionService, StoragePathService, MediaService

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logFormatter = logging.Formatter("%(name)-12s %(asctime)s %(levelname)-8s %(filename)s:%(funcName)s %(message)s")
consoleHandler = logging.StreamHandler(stdout)
consoleHandler.setFormatter(logFormatter)
logger.addHandler(consoleHandler)

# RambbitMQ Settings
username = str(os.getenv("RABBITMQ_DEFAULT_USER"))
password = str(os.getenv("RABBITMQ_DEFAULT_PASS"))
rabbit_host = str(os.getenv("RABBITMQ_DEFAULT_HOST"))

queue_in_name = str(os.getenv("QUEUE_IN_NAME"))
queue_out_name = str(os.getenv("QUEUE_OUT_NAME"))
exchange_name = str(os.getenv("EXCHANGE_NAME"))
routing_key_in = str(os.getenv("ROUTING_KEY_IN"))
routing_key_out = str(os.getenv("ROUTING_KEY_OUT"))

# Faster-Whisper Settings
model_size = str(os.getenv("MODEL_SIZE"))
device = str(os.getenv("DEVICE"))
compute_type = str(os.getenv("COMPUTE_TYPE"))
beam_size = int(os.getenv("BEAM_SIZE"))

# Directories
root_storage_path = str(os.getenv("STORAGE_PATH"))

# Init
storage_path_service = StoragePathService(root_path=root_storage_path)
transcription_service = TranscriptionService(storage_path_service=storage_path_service,
                                             model_size=model_size,
                                             device=device,
                                             compute_type=compute_type,
                                             beam_size=beam_size)
media_service = MediaService(storage=storage_path_service)
credentials = pika.credentials.PlainCredentials(username=username,
                                                password=password)


def callback(ch, method, properties, body):
    try:
        uuid = body.decode("utf-8")
        answer = {
            "uuid": uuid,
            "status": "Transcribing",
            "message": "Transcribing",
            "words": []
        }
        ch.basic_publish(exchange=exchange_name,
                         routing_key=routing_key_out,
                         body=json.dumps(answer).encode("UTF-8"))
        media_service.split_source(uuid=uuid)
        try:
            answer = transcription_service.generate_subs(uuid=uuid)
        except Exception as e:
            answer = {
                "uuid": uuid,
                "status": "Error",
                "message": "An error while an audio transcribing.",
                "words": []
            }
        ch.basic_publish(exchange=exchange_name,
                         routing_key=routing_key_out,
                         body=json.dumps(answer).encode("UTF-8"))
    except Exception as e:
        logger.error(str(e))


if __name__ == '__main__':
    channel = None
    connection = None
    while True:
        try:
            if connection is None or connection.is_closed:
                logger.info('Make new connection')
                connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbit_host,
                                                                               credentials=credentials))
            elif channel is None or channel.is_closed:
                logger.info('Make new channel')
                channel = connection.channel()
                channel.exchange_declare(exchange=exchange_name,
                                         durable=True,
                                         auto_delete=False,
                                         exchange_type=ExchangeType.direct)
                channel.queue_declare(queue=queue_in_name,
                                      durable=True)
                channel.queue_bind(exchange=exchange_name,
                                   queue=queue_in_name,
                                   routing_key=routing_key_in)
                channel.queue_declare(queue=queue_out_name,
                                      durable=True)
                channel.queue_bind(exchange=exchange_name,
                                   queue=queue_out_name,
                                   routing_key=routing_key_out)
                channel.basic_consume(queue=queue_in_name,
                                      auto_ack=True,
                                      on_message_callback=callback)
            else:
                logger.info('Waiting for messages. To exit press CTRL+C')
                channel.start_consuming()
        except Exception as e:
            logger.error(f"{str(e)}")
            time.sleep(15)  # TODO need to be reviewed
