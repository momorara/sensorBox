#!/usr/bin/python

"""
###########################################################################
駐車場に設置する
・温度、湿度
・気圧、温度
・超音波距離測定--車の有り無し
・カメラ
を設置

#Filename      :senserBox06.py
    気圧センサーは別プロセスとして起動させておく
    BMP180_Server03.py
    *デーモンとして起動する場合は
        sudo systemctl daemon-reload    ユニットをロード
        sudo systemctl start BMP180d    ユニットを起動
        sudo systemctl stop BMP180d.service　ユニットを停止

#Update        :2019/12/30
#Update        :2020/01/04
2020/01/04
    02  3つのセンサーが揃い、微調整始める
2020/01/26
    03  テスト用に乱数で数値を返すモードを作る
        テストモードで動作させるには、GPIOに何も繋げないラズパイが必要
2020/01/30
    04  仮app取り込み
2020/01/31
    04  sendMail,rcvMailでプリントしない引数を設定
        一応完成
2020/02/01
    04  メール、Line発信タイミングの微調整
2020/02/03
    05  センサーエラー処理
2020/02/16
    06  USエラーなら判定しないことにしていたが、出庫状態でエラーになるので、判定することにする。
2020/02/17
        今はメール再開停止だけだが、再開すれば状況報告するので、状況を止めて
        出庫・入庫時のみメールするモードを追加するかな
2020/03/18-20
        極たまに出庫エラーがある。ちょっと対策。計測タイミングにディレイを入れた。
        境界ラインを上げる。入出庫レベル = 1290
2020/03/22
        csvに距離も保存、距離計算を変更
2020/03/24
        距離計算変更に伴い入出庫レベル = 500　というよりセンサーの角度の問題。

############################################################################
"""

import RPi.GPIO as GPIO
import time
from nobu_LIB import Lib_etc
from nobu_LIB import Lib_LINE
from nobu_LIB import Lib_Mail
import timeout_decorator
import csv

# BMP
from time import sleep
import socket
import binascii
import subprocess
# DHT
import datetime
from nobu_LIB import Lib_dht11

from nobu_LIB import Lib_IP

import random

TRIG_PIN = 24
ECHO_PIN = 23
LEDPin = 27
instance = Lib_dht11.DHT11(pin=14)

# テスト計測値の初期値
DHT_test_t =  24
DHT_test_h =  40
BMP_test_t =   9.9
BMP_test_p = 999
US_test_d  = 150

""" 通知先メールアドレスの設定　"""
sendmail = 'nobu'


def setup():
    GPIO.setwarnings(False)
    # GPIOのピンレイアウトを設定する
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LEDPin,GPIO.OUT,initial=GPIO.LOW)
    GPIO.setup(TRIG_PIN,GPIO.OUT)
    GPIO.setup(ECHO_PIN,GPIO.IN)

# ＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊　超音波　測距　＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊
@timeout_decorator.timeout(5)
def pulseIn(PIN, start=1, end=0):
    try:
        if start==0: end = 1
        t_start = 0
        t_end = 0
        # ECHO_PINがHIGHである時間を計測
        while GPIO.input(PIN) == end:
            t_start = time.time()
        while GPIO.input(PIN) == start:
            t_end = time.time()
        #print("test finished successfully :)")
        return t_end - t_start
    except:
        print("US timed out :(")
        return 999

# 超音波測定器　距離計測
def calc_distance(mode,TRIG_PIN, ECHO_PIN, num):
    global US_test_d
    v = 34000
    if mode == 'テスト乱数':
        # 全くの乱数
        # distance = US_test_d int(random.random() * 1000 ) / 10
        # 初期値に対する+-1の乱数
        distance = round(US_test_d + random.randint(-1,1),1)
        mes = 'ok'
        return distance,mes
    try:
        dist = []
        print()
        for i in range(num):
            # TRIGピンを0.3[s]だけLOW
            GPIO.output(TRIG_PIN, GPIO.LOW)
            time.sleep(0.3)
            # TRIGピンを0.00001[s]だけ出力(超音波発射)        
            GPIO.output(TRIG_PIN, True)
            time.sleep(0.00001)
            GPIO.output(TRIG_PIN, False)
            # HIGHの時間計測
            t = pulseIn(ECHO_PIN)
            # 距離[cm] = 音速[cm/s] * 時間[s]/2
            distance = v * t/2
            dist.append(distance)
            #print(distance, "cm")
            # ちょっとsleepしてみる
            time.sleep(random.randint(0, 3))
            print('{0:.1f}cm'.format(distance),' ',end='', flush=True)
        print()

        # 10個の測定データの最大3個を削除し、残り8個の平均をとる
        dist.sort()
        del dist[7:]
        # print(len(dist))
        for i in range(len(dist)):
            print('{0:.1f}cm'.format(dist[i]),' ',end='', flush=True)
        distance = int((sum(dist) / len(dist))*10)/10
        print()
        print('計算結果=',distance,'cm')
        print()

    except:
        distance = 0
        mes = 'US_err'
        return distance,mes
    finally:
        mes = 'ok'
        if distance > 900:
            mes = 'US_err longDistance'
        return distance,mes

# ＊＊＊＊＊＊＊＊＊＊＊＊　ipアドレスを自動取得　＊＊＊＊＊＊＊＊＊＊＊＊
ip = Lib_IP.myIP()
print(ip,'**')

# ＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊　BMP180　＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊
def BMP(mode):
    if mode == 'テスト乱数':
        global BMP_test_t, BMP_test_p
        BMP_test_t = round(BMP_test_t + random.randint(-1,1)/10,1)
        BMP_test_p = round(BMP_test_p + random.randint(-1,1),1)
        # タイムスタンプなし
        msg1 = ' Temp= ' + str(BMP_test_t) + ' C Press= ' + str(BMP_test_p) + ' hPa'
        #print(msg1)
        msg = msg1.encode('utf-8')
        # msg = b'14:50 Temp= 38.8 C Press= 1038 hPa'
        return msg
    HOST = ip
    PORT = 8001
    CRLF = "\r\n"
    BMP_stat = ''
    # IPv4のTCP通信用のオブジェクトを作る
    # note: socket.AF_INET はIPv4
    # note: socket.SOCK_STREAM はTPC
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # 指定したホストとポートに接続
    # サーバープログラムが再起動した際にはソケット回復に60秒程度かかるので、リトライする。
    for i in range(1, 4):
        try:
            client.connect((HOST, PORT))
        except Exception as e:
            #print("error:{e} retry:{i}/{max}".format(e=e, i=i, max=3))
            print(' TCP_err',i,end='', flush=True)
            sleep(5)
        else:
            BMP_stat = 'ok'
            break
    if i == 3 :
        # print("BMP error end")
        BMP_stat = 'err'

    if BMP_stat == 'ok':
        send_message = "test"
        send_message += CRLF

        # バイナリで送る
        send_binary = send_message.encode()
        client.send(send_binary)

        # 流れてくるメッセージを読み込む
        recieve_messages = []
        bytes_recd = 0
        MSGLEN = 4096
        while bytes_recd < MSGLEN:
            recieve = client.recv(min(MSGLEN - bytes_recd, 2048))
            if recieve == b"":
                # とりあえず空が来たら終わる
                break
            recieve_messages.append(recieve)
            bytes_recd = bytes_recd + len(recieve)

        msg = binascii.unhexlify(b"".join(recieve_messages))
        return msg
    else:
        msg = 'BMP err'
        return msg

# ＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊　DHT11　＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊＊
@timeout_decorator.timeout(10)
def DHT(mode):
    if mode == 'テスト乱数':
        global DHT_test_t, DHT_test_h
        DHT_test_t = round(DHT_test_t + random.randint(-1,1)/10,1)
        DHT_test_h = round(DHT_test_h + random.randint(-1,1)/10,1)
        result1 = DHT_test_t
        result2 = DHT_test_h
        return result1,result2
    try:
        result1 = 0
        result2 = 0
        while result1==0:
            result = instance.read()
            if result.is_valid():
                # print("温度: %-3.1f C" % result.temperature)
                # print("湿度: %-3.1f %%" % result.humidity)
                result1 = result.temperature
                result2 = result.humidity
        #エラー処理
        #データが取れない時の処理
        return result1,result2
    except:
        print("DHT timed out :(")
        return 999,999

def make_file():
    # データ保存ファイルを作成する。
    # ファイルが無ければ作る、の'a'を指定してdata_writeでファイルを開くので
    # この関数ではヘッダーのみ記録する。
    f = open('sensorBox_data.csv', 'a',encoding="Shift_jis") 
    csvWriter = csv.writer(f)
    # csvファイルの書き込み
    csvWriter.writerow(['year','MO','D','H','MI','temp_D','temp_B','hum','press','car'])
    f.close()

def data_write(気温DHT,気温BMP,湿度DHT,気圧,距離,car):
    # データを保存する。
    # とりあえず、10分毎のデータを逐次保存
    # 20200120,1220,気温DHT,気温BMP,湿度DH,気圧,入庫or出庫
    # ファイルが無ければ作る、の'a'を指定してます。
    # csvファイルの準備
    dt_now = datetime.datetime.now()
    f = open('sensorBox_data.csv', 'a',encoding="Shift_jis") 
    csvWriter = csv.writer(f)
    # csvファイルの書き込み
    車有無 = 0
    if car == '入庫':車有無 = 1
    csvWriter.writerow([dt_now.year,dt_now.month,dt_now.day,dt_now.hour,dt_now.minute,気温DHT,気温BMP,湿度DHT,気圧,距離,車有無])
    f.close()

#main function
def main():
    # プログラム起動報告
    Lib_LINE.Line_sendMessage('sensorBox 起動しました。 ' ,' token_kakunin')

    make_file()

    # 計測タイミングを設定
    sokutei_time = [0,10,20,30,40,50] #測定 の周期
    sokutei_time = [0,10,20,30,40,50,5,15,25,35,45,55] #測定 の周期 テスト用　高周期
    # 定期Line送信
    Line_time = [20] #Line の周期　sokutei_time内であることが条件
    mail_check_time = [4,14,24,34,44,54]  
    # 車距離測定し初期設定
    GPIO.output(LEDPin,GPIO.HIGH)
    distance,mes = calc_distance('本番',TRIG_PIN, ECHO_PIN, 10)
    GPIO.output(LEDPin,GPIO.LOW)

    入出庫レベル = 500
    car,car_past = '入庫','入庫'
    if distance > 入出庫レベル :car,car_past = '出庫','出庫'
    print(distance,car)

    mail_flag = 0 # 1:メール送信　0:メール停止　初期設定ではメールしない。
    car_mail_flag = 1 # 車の入出庫時にメールをする　1:メール送信　0:メール停止

    mail_n = 3 # 取得するメールの数
    chkString_1 = "センサーボックスメール再開"      # flag 5
    chkString_2 = "センサーボックスメール停止"      # flag 2
    chkString_3 = "センサーボックス車メール再開"    # flag 3
    chkString_4 = "センサーボックス緊急停止"        # flag 4

    count = 0
    # 同じ測定時間では一度だけ測定する。
    one_time = -1
    one_mail_check = -1
    one_Line = -1

    while True:

        dt_now = datetime.datetime.now()
        time_now = str(dt_now.hour) + "時" + str(dt_now.minute) +  "分 " 
        # print('status ',time_now,)

        # if True:
        if (dt_now.minute in sokutei_time) and (one_time != dt_now.minute) :
            one_time = dt_now.minute
            # *******************************
            GPIO.output(LEDPin,GPIO.HIGH)

            # 温度・湿度測定 DHT11
            気温DHT,湿度DHT = DHT('本番')
            if 気温DHT == 999:
                # DHTエラーなら5秒待って、再度計測
                time.sleep(5)
                気温DHT,湿度DHT = DHT('本番')

            # 気圧・温度測定 BMP180
            result = BMP('本番')
            BMPデータ = result.decode('utf-8')
            if BMPデータ ==  'BMP err':
                # BMPエラーなら5秒待って、再度計測
                time.sleep(5)
                result = BMP('本番')
                BMPデータ = result.decode('utf-8')
            # BMPデータから気温と気圧を切り出し、数値にする。
            気温BMP = float(BMPデータ[BMPデータ.find('=')+2 :BMPデータ.find('=')+6])
            気圧    = int  (BMPデータ[BMPデータ.find('s=')+3:BMPデータ.find('s=')+7])

            """
            ここで　DS18B20　温度を取得　気温DS18B20
            もし、DS18B20の温度が正確ならこれだけにしてもいい
            DHTとほぼ同値なので、もういいかな　20-27度
            """

            # 車距離計測
            distance,mes = calc_distance('本番',TRIG_PIN, ECHO_PIN, 10)
            if mes != 'ok':
                # USエラーなら5秒待って、再度計測
                time.sleep(5)
                distance,mes = calc_distance('本番',TRIG_PIN, ECHO_PIN, 10)

            GPIO.output(LEDPin,GPIO.LOW)
            # *******************************

            # USエラーなら判定しないことにしていたが、出庫状態で2100cm エラーになるので、判定することにする。
            # if mes == 'ok':
            if distance > 入出庫レベル :
                car = '出庫'
            else:
                car = '入庫'
            if car_past != car:
                # 変化あり
                car_past = car
                # 入庫、出庫変化があった場合の処理
                # LINE、メールで入庫、出庫を連絡する。
                Lib_LINE.Line_sendMessage(car + 'しました。' ,' token_kakunin')
                if mail_flag == 1 or car_mail_flag == 1:
                    Lib_Mail.sendMail(sendmail,car + 'しました。' + str(distance) + 'cm',0)
                    print(car + 'しました。' + str(distance) + 'cm')

            data_write(気温DHT,気温BMP,湿度DHT,気圧,distance,car)
            msg = BMPデータ + ' ' + str(気温DHT) + '度 ' + str(湿度DHT) + '% ' + car + str(distance) + 'cm'
            print(msg)
            if mail_flag == 1:
                Lib_Mail.sendMail(sendmail,msg,0)

            #　Line_timeにlineが来ないので、修正
            # if (dt_now.minute in Line_time) and (one_Line != dt_now.minute) :
            if (dt_now.minute in Line_time) :
                Lib_LINE.Line_sendMessage(msg ,' token_kakunin',0)

        dt_now = datetime.datetime.now()
        if (dt_now.minute in mail_check_time) and (one_mail_check != dt_now.minute):
            one_mail_check = dt_now.minute
            # cometsum のメールを確認する。
            flag = Lib_Mail.rcvMail(mail_n,chkString_1,chkString_2,chkString_3,chkString_4,0)
            #print('mail_flag= ',flag)
        
            # "制御指示メールが来ていたら、制御を実行

            #　"センサーボックスメール再開" 
            if flag == 5: 
                mail_flag = 1
                Lib_Mail.sendMail(sendmail,'センサーボックスメール再開しました。 ' )
                print('センサーボックスメール再開しました。 ' )

            #　"センサーボックスメール停止"
            if flag == 2: 
                mail_flag = 0
                car_mail_flag = 0
                Lib_Mail.sendMail(sendmail,'センサーボックスメール、車メール停止しました。 ' )
                print('センサーボックスメール、車メール停止しました。 ' )

            #　"センサーボックス車メール再開"  
            if flag == 3:
                Lib_LINE.Line_sendMessage('センサーボックス車メール再開しました。 ' ,' token_kakunin')
                Lib_Mail.sendMail(sendmail,'センサーボックス車メール再開しました。 ' )
                print('センサーボックス車メール再開を受信しました。 ' )
                print(BMPデータ , 気温DHT , '度 ' , 湿度DHT , '% ',car)
                Lib_Mail.sendMail(sendmail,BMPデータ + ' ' + str(気温DHT) + '度 ' + str(湿度DHT) + '% ' + car )
                car_mail_flag = 1

            #　"センサーボックス緊急停止" 
            if flag == 4:
                Lib_Mail.sendMail(sendmail,BMPデータ + ' ' + str(気温DHT) + '度 ' + str(湿度DHT) + '% ' + car )
                Lib_LINE.Line_sendMessage('センサーボックス緊急停止。  確認用'  ,' token_kakunin')
                Lib_Mail.sendMail(sendmail,'センサーボックス緊急停止。' )
                print('センサーボックス緊急停止。' )
                raise ValueError("センサーボックス緊急停止!!")

        # プログラム動作確認　LED
        if count % 3 == 0 : Lib_etc.LED_flash27(0.05,0.05,5)
        count += 1

        time.sleep(5)

def destroy():
    #turn off LED
    GPIO.output(LEDPin,GPIO.LOW)
    #release resource
    GPIO.cleanup()

if __name__ == '__main__':
    setup()
    try:
        main()
        #when 'Ctrl+C' is pressed,child program destroy() will be executed.
    except KeyboardInterrupt:
        destroy()
    pass
    
