/*
  UrbanEye - ESP32-CAM Firmware (Tailored for RHYX M21-45 / GC2145 & OV2640 Sensors)
  Hardware: ESP32-CAM (AI-Thinker module with RHYX M21-45 / GC2145 or OV2640)
  
  Why this specialized sketch is needed:
  The RHYX M21-45 sensor (GalaxyCore GC2145) does NOT have hardware JPEG encoding.
  This firmware initializes the sensor in RGB565 / YUV422 and utilizes the onboard
  ESP32 software JPEG converter (img_converters.h) to produce a high-speed MJPEG
  stream over Wi-Fi for UrbanEye.
*/

#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"
#include "img_converters.h" // Software JPEG converter for RHYX M21-45 (GC2145)

// =================== WI-FI CONFIGURATION ===================
const char* ssid = "YOUR_WIFI_SSID";          // Replace with your Wi-Fi name (2.4 GHz)
const char* password = "YOUR_WIFI_PASSWORD";  // Replace with your Wi-Fi password
// ===========================================================

// AI-Thinker Camera Pin Map
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// Flash LED pin
#define FLASH_LED_PIN      4

#define PART_BOUNDARY "123456789000000000000987654321"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

httpd_handle_t stream_httpd = NULL;

static esp_err_t stream_handler(httpd_req_t *req) {
  camera_fb_t * fb = NULL;
  esp_err_t res = ESP_OK;
  size_t _jpg_buf_len = 0;
  uint8_t * _jpg_buf = NULL;
  bool is_converted = false;
  char * part_buf[64];

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  if(res != ESP_OK){
    return res;
  }

  while(true){
    fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("[ESP32-CAM] Frame capture failed");
      res = ESP_FAIL;
    } else {
      // If hardware JPEG is available (e.g. OV2640), use directly
      if (fb->format == PIXFORMAT_JPEG) {
        _jpg_buf = fb->buf;
        _jpg_buf_len = fb->len;
        is_converted = false;
      } else {
        // RHYX M21-45 (GC2145) outputs RGB565/YUV422 -> convert to JPEG on the fly
        is_converted = frame2jpg(fb, 80, &_jpg_buf, &_jpg_buf_len);
        if (!is_converted) {
          Serial.println("[ESP32-CAM] Software JPEG conversion failed");
          res = ESP_FAIL;
        }
      }
    }

    if(res == ESP_OK){
      size_t hlen = snprintf((char *)part_buf, 64, _STREAM_PART, _jpg_buf_len);
      res = httpd_resp_send_chunk(req, (const char *)part_buf, hlen);
    }
    if(res == ESP_OK){
      res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
    }
    if(res == ESP_OK){
      res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
    }

    // Clean up dynamically allocated JPEG buffer from frame2jpg
    if (is_converted && _jpg_buf) {
      free(_jpg_buf);
      _jpg_buf = NULL;
    }

    if(fb){
      esp_camera_fb_return(fb);
      fb = NULL;
    }

    if(res != ESP_OK){
      break;
    }
  }
  return res;
}

void startCameraServer(){
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 81;

  httpd_uri_t stream_uri = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_handler,
    .user_ctx  = NULL
  };

  Serial.printf("[ESP32-CAM] Starting MJPEG stream server on port: '%d'\n", config.server_port);
  if (httpd_start(&stream_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(stream_httpd, &stream_uri);
  }
}

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println("\n==================================================");
  Serial.println(" [UrbanEye] ESP32-CAM (RHYX M21-45 / GC2145 Mode)");
  Serial.println("==================================================");

  pinMode(FLASH_LED_PIN, OUTPUT);
  digitalWrite(FLASH_LED_PIN, LOW); // Flash LED off by default

  // Hardware reset pulse to wake up camera sensor
  pinMode(PWDN_GPIO_NUM, OUTPUT);
  digitalWrite(PWDN_GPIO_NUM, HIGH); // Power down
  delay(20);
  digitalWrite(PWDN_GPIO_NUM, LOW);  // Power up
  delay(50);

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  
  // 10MHz clock for RHYX M21-45 stability
  config.xclk_freq_hz = 10000000;

  // IMPORTANT FOR RHYX M21-45 (GC2145):
  // RHYX M21-45 does NOT have hardware JPEG. We configure RGB565.
  config.pixel_format = PIXFORMAT_RGB565;
  config.frame_size = FRAMESIZE_QVGA; // 320x240 (ideal for raw buffer and CPU conversion)
  config.fb_count = 1;

  if(psramFound()){
    Serial.println("[ESP32-CAM] PSRAM detected!");
  } else {
    Serial.println("[ESP32-CAM] Notice: Running on internal SRAM");
  }

  // First try initializing in RGB565 (for RHYX M21-45 / GC2145)
  esp_err_t err = esp_camera_init(&config);
  
  // If RGB565 fails, fallback to YUV422
  if (err != ESP_OK) {
    Serial.printf("[ESP32-CAM] RGB565 init returned 0x%x. Trying YUV422...\n", err);
    config.pixel_format = PIXFORMAT_YUV422;
    err = esp_camera_init(&config);
  }

  if (err != ESP_OK) {
    Serial.printf("[ESP32-CAM] Camera init failed with error 0x%x\n", err);
    return;
  }
  Serial.println("[ESP32-CAM] RHYX M21-45 sensor initialized successfully!");

  // Connect to Wi-Fi
  WiFi.begin(ssid, password);
  Serial.print("[ESP32-CAM] Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n[ESP32-CAM] Wi-Fi connected successfully!");
  
  // Start Streaming Server
  startCameraServer();

  Serial.println("==================================================");
  Serial.print("UrbanEye Stream Ready: http://");
  Serial.print(WiFi.localIP());
  Serial.println(":81/stream");
  Serial.println("==================================================");
}

void loop() {
  delay(10000);
}
