package com.personalassistant.companion;

import java.util.Arrays;

public final class PageHistoryHarness {
    static void equal(int expected,int actual){if(expected!=actual)throw new AssertionError(expected+" != "+actual);}
    public static void main(String[] args){
        PageHistory h=new PageHistory();
        equal(-1,h.back(0)); // Home may leave the app when there is no previous page.
        equal(0,h.back(2)); // A direct entry returns Home.
        h.visit(0,1);h.visit(1,4);h.visit(4,4);h.visit(4,2);
        equal(4,h.back(2));equal(1,h.back(4));equal(0,h.back(1));equal(-1,h.back(0));
        h.visit(0,3);h.visit(3,0); // Going Home manually still preserves the last page.
        equal(3,h.back(0));equal(0,h.back(3));
        h.visit(0,2);h.visit(2,3);
        PageHistory recreated=new PageHistory();recreated.restore(h.save());
        equal(2,recreated.back(3));equal(0,recreated.back(2));equal(-1,recreated.back(0));
        recreated.restore(new int[]{-1,8,1,4});equal(4,recreated.back(2));equal(1,recreated.back(4));
        for(int i=0;i<200;i++)h.visit(i%5,(i+1)%5);
        equal(32,h.save().length);h.clear();equal(0,h.back(4));equal(-1,h.back(0));
        System.out.println("Page history passed");
    }
}
