package com.blendengine.export;
import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
public class MainActivity extends Activity {
  public void onCreate(Bundle b){ super.onCreate(b); WebView v=new WebView(this); WebSettings s=v.getSettings(); s.setJavaScriptEnabled(true); s.setAllowFileAccess(true); setContentView(v); v.loadUrl("file:///android_asset/web_player/index.html"); }
}
