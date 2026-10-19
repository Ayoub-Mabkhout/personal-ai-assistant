package com.personalassistant.companion;

import android.content.Context;
import android.graphics.Color;
import android.view.Gravity;
import android.view.View;
import android.widget.*;

/** Bundled brand marks only: viewing a transaction never contacts a logo service. */
final class MerchantMarks {
    private MerchantMarks(){}
    static View create(Context context,AppUi ui,String brand,String name){
        if(brand!=null&&brand.matches("[a-z-]{2,30}")){
            int resource=context.getResources().getIdentifier("merchant_"+brand.replace('-','_'),"drawable",context.getPackageName());
            if(resource!=0){FrameLayout tile=new FrameLayout(context);tile.setBackground(ui.outline(Color.WHITE,12,0,0));ImageView image=new ImageView(context);image.setImageResource(resource);image.setContentDescription(name);FrameLayout.LayoutParams size=new FrameLayout.LayoutParams(ui.dp(24),ui.dp(24),Gravity.CENTER);tile.addView(image,size);return tile;}
        }
        TextView text=new TextView(context);String[] words=name.trim().split("\\s+");String mark="";for(String word:words)if(!word.isEmpty()){mark+=word.substring(0,1);if(mark.length()==2)break;}text.setText(mark.toUpperCase(java.util.Locale.ROOT));text.setGravity(Gravity.CENTER);text.setTextColor(ui.accent);text.setTextSize(12);text.setBackground(ui.outline(ui.surfaceAlt,12,0,0));return text;
    }
}
